import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pymupdf
from fastapi import HTTPException
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from markitdown import MarkItDown

from app.config import settings
from app.typing.schemas import ChunkData, IngestResponse, SummarizedChunk
from app.utils import mongodb
from app.utils.mongodb import create_project
from app.utils.text_splitters import get_splitter

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".html", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}


def detect_document_type(file_path: str) -> str:
    """Detect document type from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext in (".html", ".htm"):
        return "html"
    return ext.lstrip(".") or "txt"


def get_page_count(file_path: str) -> int:
    """Get page count for PDFs, return 0 for other types."""
    ext = Path(file_path).suffix.lower()
    if ext != ".pdf":
        return 0
    try:
        doc = pymupdf.open(file_path)
        page_count = len(doc)
        doc.close()
        return page_count
    except Exception as e:
        logger.warning(f"Failed to get page count: {e}")
        return 0


async def extract_text_by_page(file_path: str, use_ocr: bool | None = None) -> list[dict]:
    """Extract text per page for PDFs/DOCX/PPTX. Returns list of {text, page_number}.
    
    For PDFs: Extract directly with pymupdf
    For DOCX/PPTX: Convert to PDF first, then extract
    For TXT/HTML: Return full content with page_number=None
    """
    ext = Path(file_path).suffix.lower()
    
    if ext == ".pdf":
        doc = pymupdf.open(file_path)
        page_texts = []
        total_text_length = 0
        total_images = 0
        
        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            images = page.get_images()
            
            if text.strip():
                page_texts.append({"text": text, "page_number": page_num})
                total_text_length += len(text.strip())
            
            total_images += len(images)
        
        doc.close()
        
        logger.info(
            f"PDF extraction: {total_text_length} chars of text, {total_images} images found in {file_path}"
        )
        
        should_ocr = use_ocr if use_ocr is not None else (total_text_length < settings.ocr_text_threshold)
        if should_ocr and total_images > 0:
            logger.info(
                f"PDF appears to be a scanned document (text < {settings.ocr_text_threshold} chars, has {total_images} images), "
                f"attempting OCR for: {file_path}"
            )
            try:
                from openai import OpenAI
                client = OpenAI(
                    api_key=settings.openrouter_api_key,
                    base_url=settings.openrouter_base_url,
                )
                md = MarkItDown(
                    enable_plugins=True,
                    llm_client=client,
                    llm_model=settings.vision_model or settings.llm_model,
                )
                result = await asyncio.wait_for(
                    asyncio.to_thread(md.convert, file_path),
                    timeout=120.0
                )
                if result.text_content and result.text_content.strip():
                    logger.info(f"OCR successfully extracted {len(result.text_content)} chars from scanned PDF")
                    return [{"text": result.text_content, "page_number": 1}]
                else:
                    logger.warning(f"OCR failed to extract text from scanned PDF: {file_path}")
                    return []
            except TimeoutError:
                logger.warning(f"OCR timed out after 120 seconds for {file_path}")
                return []
            except Exception:
                logger.exception(f"OCR failed for {file_path}")
                return []
        
        return page_texts
    
    elif ext in {".docx"}:
        from app.utils.conversion_utils import docx_to_pdf
        
        try:
            pdf_bytes, _ = docx_to_pdf(file_path)
        except Exception:
            from app.utils.conversion_utils import docx_to_pdf_via_mammoth
            pdf_bytes, _ = docx_to_pdf_via_mammoth(file_path)
        
        doc = pymupdf.open("pdf", pdf_bytes)
        page_texts = []
        for page_num, page in enumerate(doc, 1):
            text = page.get_text()
            if text.strip():
                page_texts.append({"text": text, "page_number": page_num})
        doc.close()
        return page_texts
    
    else:
        md = MarkItDown()
        result = await asyncio.to_thread(md.convert, file_path)
        return [{"text": result.text_content, "page_number": None}]


async def ingestion_pipeline_stream(
    file_path: str | None,
    filename: str,
    project_name: str,
    user_id: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    text_splitter: str | None = None,
    embedding_model: str | None = None,
    transcript_text: str | None = None,
    use_ocr: bool | None = None,
) -> AsyncGenerator[tuple[str, dict], None]:
    """Streaming ingestion pipeline that yields progress events.
    
    Yields:
        (event_type, data) tuples where event_type is one of:
        - "stage": data = {"stage": str}
        - "progress": data = {"percent": float, "stage": str}
        - "done": data = IngestResponse dict
        - "error": data = {"message": str}
    """
    try:
        existing_count = await mongodb.vectors.count_documents(
            {"user_id": user_id, "project_name": project_name}
        )

        yield ("stage", {"stage": "partition"})

        if transcript_text:
            document_type = "txt"
            page_texts = [{"text": transcript_text, "page_number": None}]
            yield ("progress", {"percent": 50, "stage": "partition"})
        else:
            document_type = detect_document_type(file_path)
            page_texts = await extract_text_by_page(file_path, use_ocr)
            yield ("progress", {"percent": 100, "stage": "partition"})

        no_of_pages = len([p for p in page_texts if p["page_number"] is not None])

        resolved_chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
        resolved_chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
        resolved_splitter = text_splitter or settings.text_splitter

        yield ("stage", {"stage": "chunk"})

        final_chunks = []
        
        for page_data in page_texts:
            page_text = page_data["text"]
            page_number = page_data["page_number"]
            
            if resolved_splitter == "markdown_header":
                header_splitter = MarkdownHeaderTextSplitter(
                    headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
                )
                header_chunks = header_splitter.split_text(page_text)

                recursive_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=resolved_chunk_size,
                    chunk_overlap=resolved_chunk_overlap,
                    length_function=len,
                    separators=["\n\n", "\n", " ", ""],
                )

                page_chunks = []
                for chunk in header_chunks:
                    if len(chunk.page_content) > settings.oversized_threshold:
                        sub_chunks = recursive_splitter.split_documents([chunk])
                        page_chunks.extend(sub_chunks)
                    else:
                        page_chunks.append(chunk)

            else:
                splitter = get_splitter(resolved_splitter, resolved_chunk_size, resolved_chunk_overlap)
                split_result = splitter.split_text(page_text)
                
                if hasattr(split_result[0], 'page_content'):
                    page_chunks = split_result
                else:
                    from langchain_core.documents import Document
                    page_chunks = [Document(page_content=text) for text in split_result]
            
            for chunk in page_chunks:
                chunk.metadata["page_number"] = page_number
            
            final_chunks.extend(page_chunks)
        
        if not final_chunks:
            logger.warning("Text splitter produced zero chunks for: %s", filename)
            yield ("error", {"message": "Document produced no content after splitting"})
            return

        yield ("progress", {"percent": 100, "stage": "chunk"})

        yield ("stage", {"stage": "vectorize"})

        for i, chunk in enumerate(final_chunks):
            chunk.metadata.update({
                "source": filename,
                "chunk_index": existing_count + i,
                "total_chunks": existing_count + len(final_chunks),
            })

        texts = [chunk.page_content for chunk in final_chunks]

        for attempt in range(2):
            try:
                yield ("progress", {"percent": 20, "stage": "vectorize"})
                embeddings_instance = mongodb.get_embeddings(embedding_model)
                embedding_vectors = await asyncio.wait_for(
                    asyncio.to_thread(embeddings_instance.embed_documents, texts),
                    timeout=120.0
                )
                break
            except Exception as e:
                if attempt == 1:
                    raise
                logger.warning("Embedding attempt %s failed: %s, retrying...", attempt + 1, e)

        yield ("progress", {"percent": 60, "stage": "vectorize"})

        now = datetime.now(UTC)
        docs_to_insert = []
        for i, (chunk, vector) in enumerate(zip(final_chunks, embedding_vectors)):
            doc = {
                "user_id": user_id,
                "project_name": project_name,
                "chunk_index": existing_count + i,
                "content": chunk.page_content,
                "embedding": vector,
                "metadata": chunk.metadata,
                "created_at": now,
            }
            docs_to_insert.append(doc)

        await mongodb.vectors.insert_many(docs_to_insert)

        yield ("progress", {"percent": 90, "stage": "vectorize"})

        existing_project = await mongodb.projects.find_one(
            {"user_id": user_id, "project_name": project_name}
        )
        
        if existing_project:
            documents = existing_project.get("documents", [])
            existing_doc = next((d for d in documents if d["name"] == filename), None)
            
            if existing_doc:
                await mongodb.projects.update_one(
                    {"user_id": user_id, "project_name": project_name},
                    {
                        "$set": {
                            "chunk_count": existing_count + len(docs_to_insert),
                            "documents.$[elem].chunk_count": existing_doc["chunk_count"] + len(docs_to_insert),
                        },
                    },
                    array_filters=[{"elem.name": filename}]
                )
            else:
                new_doc = {
                    "name": filename,
                    "type": document_type,
                    "chunk_count": len(docs_to_insert),
                    "uploaded_at": datetime.now(UTC),
                }
                await mongodb.projects.update_one(
                    {"user_id": user_id, "project_name": project_name},
                    {
                        "$push": {"documents": new_doc},
                        "$set": {"chunk_count": existing_count + len(docs_to_insert)},
                    }
                )
        else:
            await create_project(
                user_id=user_id,
                name=filename,
                project_name=project_name,
                documents=[{
                    "name": filename,
                    "type": document_type,
                    "chunk_count": len(docs_to_insert),
                    "uploaded_at": datetime.now(UTC),
                }],
                chunk_count=len(docs_to_insert),
            )

        yield ("progress", {"percent": 100, "stage": "vectorize"})

        chunks = [
            ChunkData(
                text=chunk.page_content,
                types=["text"],
                tables=[],
                images=[],
            )
            for chunk in final_chunks
        ]

        summarized_chunks = [
            SummarizedChunk(
                page_content=chunk.page_content,
                metadata={
                    "chunk_id": str(i),
                    "source": filename,
                    "chunk_index": i,
                },
            )
            for i, chunk in enumerate(final_chunks)
        ]

        response = IngestResponse(
            status="ok",
            chunk_count=len(docs_to_insert),
            document_type=document_type,
            no_of_pages=no_of_pages,
            first_chunk_index=existing_count,
            last_chunk_index=existing_count + len(docs_to_insert) - 1 if len(docs_to_insert) > 0 else existing_count,
            chunks=chunks,
            summarized_chunks=summarized_chunks,
        )

        yield ("done", response.model_dump())

    except ValueError as e:
        logger.warning("Collection uniqueness violation: %s", e)
        yield ("error", {"message": str(e)})
    except Exception as e:
        logger.exception("Ingestion pipeline failed")
        yield ("error", {"message": str(e)})


async def ingestion_pipeline(
    file_path: str | None,
    filename: str,
    project_name: str,
    user_id: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    text_splitter: str | None = None,
    transcript_text: str | None = None,
) -> tuple[int, str, int, int, list[ChunkData], list[SummarizedChunk]]:
    """Non-streaming wrapper for backward compatibility."""
    result = None
    async for event_type, data in ingestion_pipeline_stream(
        file_path=file_path,
        filename=filename,
        project_name=project_name,
        user_id=user_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        text_splitter=text_splitter,
        transcript_text=transcript_text,
    ):
        if event_type == "done":
            result = data
        elif event_type == "error":
            raise HTTPException(status_code=400, detail=data["message"])

    if result is None:
        raise HTTPException(status_code=500, detail="Ingestion failed")

    resp = IngestResponse(**result)
    return (
        resp.chunk_count,
        resp.document_type,
        resp.no_of_pages,
        resp.first_chunk_index,
        resp.chunks,
        resp.summarized_chunks,
    )

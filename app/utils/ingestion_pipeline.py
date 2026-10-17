import asyncio
import logging
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
from app.typing.schemas import ChunkData, SummarizedChunk
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


async def extract_text_by_page(file_path: str) -> list[dict]:
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
        
        # Trigger OCR if minimal text AND has images (scanned document)
        if total_text_length < settings.ocr_text_threshold and total_images > 0:
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
                result = await asyncio.to_thread(md.convert, file_path)
                if result.text_content and result.text_content.strip():
                    logger.info(f"OCR successfully extracted {len(result.text_content)} chars from scanned PDF")
                    return [{"text": result.text_content, "page_number": 1}]
                else:
                    logger.warning(f"OCR failed to extract text from scanned PDF: {file_path}")
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


async def ingestion_pipeline(
    file_path: str | None,
    filename: str,
    collection_name: str,
    user_id: str,
    project_name: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    text_splitter: str | None = None,
    transcript_text: str | None = None,
) -> tuple[int, str, int, list[ChunkData], list[SummarizedChunk]]:
    """Convert document to markdown, chunk, and store in MongoDB vector database.
    
    Args:
        file_path: Path to uploaded file (None for transcript ingestion)
        transcript_text: Raw text to ingest directly (skips file extraction)
    
    Returns:
        tuple: (chunk_count, document_type, no_of_pages, first_chunk_index, chunks, summarized_chunks)
    """
    # Get existing chunk count for this collection
    existing_count = await mongodb.vectors.count_documents(
        {"user_id": user_id, "collection_name": collection_name}
    )

    if transcript_text:
        document_type = "txt"
        page_texts = [{"text": transcript_text, "page_number": None}]
    else:
        document_type = detect_document_type(file_path)
        page_texts = await extract_text_by_page(file_path)
    no_of_pages = len([p for p in page_texts if p["page_number"] is not None])

    resolved_chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
    resolved_chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap
    resolved_splitter = text_splitter or settings.text_splitter

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
        raise HTTPException(status_code=400, detail="Document produced no content after splitting")
    
    # Assign chunk indices starting from existing_count (for append) or 0 (for new)
    for i, chunk in enumerate(final_chunks):
        chunk.metadata.update({
            "source": filename,
            "chunk_index": existing_count + i,
            "total_chunks": existing_count + len(final_chunks),
        })

    texts = [chunk.page_content for chunk in final_chunks]

    for attempt in range(2):
        try:
            embedding_vectors = await asyncio.wait_for(
                asyncio.to_thread(mongodb.embeddings.embed_documents, texts),
                timeout=120.0
            )
            break
        except Exception as e:
            if attempt == 1:
                raise
            logger.warning("Embedding attempt %s failed: %s, retrying...", attempt + 1, e)

    now = datetime.now(UTC)
    docs_to_insert = []
    for i, (chunk, vector) in enumerate(zip(final_chunks, embedding_vectors)):
        doc = {
            "user_id": user_id,
            "collection_name": collection_name,
            "chunk_index": existing_count + i,
            "content": chunk.page_content,
            "embedding": vector,
            "metadata": chunk.metadata,
            "created_at": now,
        }
        docs_to_insert.append(doc)

    await mongodb.vectors.insert_many(docs_to_insert)

    # Check if project already exists
    existing_project = await mongodb.projects.find_one(
        {"user_id": user_id, "collection_name": collection_name}
    )
    
    if existing_project:
        # Append: update chunk_count and file_name (comma-separated)
        existing_file_names = existing_project.get("file_name", "")
        new_file_names = f"{existing_file_names}, {filename}" if existing_file_names else filename
        
        await mongodb.projects.update_one(
            {"user_id": user_id, "collection_name": collection_name},
            {
                "$set": {
                    "chunk_count": existing_count + len(docs_to_insert),
                    "file_name": new_file_names,
                }
            }
        )
    else:
        # Create new project
        await create_project(
            user_id=user_id,
            name=project_name or filename,
            collection_name=collection_name,
            file_name=filename,
            chunk_count=len(docs_to_insert),
            document_type=document_type,
        )

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

    return len(docs_to_insert), document_type, no_of_pages, existing_count, chunks, summarized_chunks

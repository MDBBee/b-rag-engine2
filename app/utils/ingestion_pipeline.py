import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

from markitdown import MarkItDown
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter

from app.config import settings
from app.utils import mongodb
from app.utils.mongodb import check_collection_exists
from app.typing.schemas import ChunkData, SummarizedChunk

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".html"}


def detect_document_type(file_path: str) -> str:
    """Detect document type from file extension."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    elif ext == ".docx":
        return "docx"
    elif ext == ".txt":
        return "txt"
    elif ext in (".html", ".htm"):
        return "html"
    return "txt"


def get_page_count(file_path: str) -> int:
    """Get page count for PDFs, return 0 for other types."""
    ext = Path(file_path).suffix.lower()
    if ext != ".pdf":
        return 0
    try:
        import fitz
        doc = fitz.open(file_path)
        page_count = len(doc)
        doc.close()
        return page_count
    except Exception as e:
        logger.warning(f"Failed to get page count: {e}")
        return 0


async def ingestion_pipeline(
    file_path: str,
    filename: str,
    collection_name: str,
    user_id: str,
    embedding_model: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> tuple[int, str, int, list[ChunkData], list[SummarizedChunk]]:
    """Convert document to markdown, chunk, and store in MongoDB vector database.
    
    Returns:
        tuple: (chunk_count, document_type, no_of_pages, chunks, summarized_chunks)
    """
    logger.info(f"Ingesting document: {filename} -> collection: {collection_name} (user: {user_id})")

    if await check_collection_exists(user_id, collection_name):
        raise ValueError(f"Collection '{collection_name}' already exists for user '{user_id}'")

    document_type = detect_document_type(file_path)
    no_of_pages = get_page_count(file_path)
    logger.info(f"Document type: {document_type}, pages: {no_of_pages}")

    md = MarkItDown()
    result = await asyncio.to_thread(md.convert, file_path)
    markdown_text = result.text_content
    logger.info(f"Converted to markdown: {len(markdown_text)} chars")

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    )
    header_chunks = header_splitter.split_text(markdown_text)
    logger.info(f"Pass 1 (header split): {len(header_chunks)} chunks")

    resolved_chunk_size = chunk_size if chunk_size is not None else settings.chunk_size
    resolved_chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.chunk_overlap

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    final_chunks = []
    oversized_count = 0
    for chunk in header_chunks:
        if len(chunk.page_content) > settings.oversized_threshold:
            oversized_count += 1
            sub_chunks = recursive_splitter.split_documents([chunk])
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    logger.info(f"Pass 2 (recursive fallback): {oversized_count} oversized chunks split further")

    for i, chunk in enumerate(final_chunks):
        chunk.metadata.update({
            "source": filename,
            "chunk_index": i,
            "total_chunks": len(final_chunks),
        })

    texts = [chunk.page_content for chunk in final_chunks]
    logger.info(f"Embedding {len(texts)} chunks...")
    
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
            logger.warning(f"Embedding attempt {attempt + 1} failed: {e}, retrying...")

    now = datetime.now(timezone.utc)
    docs_to_insert = []
    for i, (chunk, vector) in enumerate(zip(final_chunks, embedding_vectors)):
        doc = {
            "user_id": user_id,
            "collection_name": collection_name,
            "chunk_index": i,
            "content": chunk.page_content,
            "embedding": vector,
            "metadata": chunk.metadata,
            "created_at": now,
        }
        docs_to_insert.append(doc)

    await mongodb.vectors.insert_many(docs_to_insert)
    logger.info(f"Stored {len(docs_to_insert)} chunks in MongoDB (user: {user_id}, collection: {collection_name})")

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

    return len(docs_to_insert), document_type, no_of_pages, chunks, summarized_chunks

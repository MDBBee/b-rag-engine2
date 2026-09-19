import asyncio
import logging

import chromadb
from markitdown import MarkItDown
from langchain_text_splitters import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_chroma import Chroma

from app.config import settings
from app.utils.factories import get_embeddings, get_vectorstore

logger = logging.getLogger(__name__)


async def ingest_document(file_path: str, filename: str, collection_name: str) -> int:
    """Convert document to markdown, chunk, and store in vector database."""
    logger.info(f"Ingesting document: {filename} -> collection: {collection_name}")

    md = MarkItDown()
    result = await asyncio.to_thread(md.convert, file_path)
    markdown_text = result.text_content
    logger.info(f"Converted to markdown: {len(markdown_text)} chars")

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    )
    header_chunks = await asyncio.to_thread(header_splitter.split_text, markdown_text)
    logger.info(f"Pass 1 (header split): {len(header_chunks)} chunks")

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", " ", ""],
    )

    final_chunks = []
    oversized_count = 0
    for chunk in header_chunks:
        if len(chunk.page_content) > settings.oversized_threshold:
            oversized_count += 1
            sub_chunks = await asyncio.to_thread(recursive_splitter.split_documents, [chunk])
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

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    try:
        collection = client.get_collection(collection_name)
        count = collection.count()
        logger.info(f"Deleting existing collection: {collection_name} ({count} docs)")
        client.delete_collection(collection_name)
    except ValueError:
        pass

    vectorstore = get_vectorstore(collection_name)

    await asyncio.to_thread(
        Chroma.from_documents,
        documents=final_chunks,
        embedding=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
        collection_name=collection_name,
    )

    logger.info(f"Stored {len(final_chunks)} chunks in collection: {collection_name}")
    return len(final_chunks)

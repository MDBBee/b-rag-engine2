from pathlib import Path
from markitdown import MarkItDown
from langchain.text_splitter import RecursiveCharacterTextSplitter, MarkdownHeaderTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings


def ingest_document(file_path: str, filename: str, collection_name: str) -> int:
    md = MarkItDown()
    result = md.convert(file_path)
    markdown_text = result.text_content

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
    )
    header_chunks = header_splitter.split_text(markdown_text)

    recursive_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    final_chunks = []
    for chunk in header_chunks:
        if len(chunk.page_content) > settings.oversized_threshold:
            sub_chunks = recursive_splitter.split_documents([chunk])
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    for i, chunk in enumerate(final_chunks):
        chunk.metadata.update({
            "source": filename,
            "chunk_index": i,
            "total_chunks": len(final_chunks),
        })

    embeddings = OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
    )

    Chroma.from_documents(
        documents=final_chunks,
        embedding=embeddings,
        persist_directory=settings.chroma_persist_dir,
        collection_name=collection_name,
    )

    return len(final_chunks)

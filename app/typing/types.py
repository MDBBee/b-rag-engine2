from typing import TypedDict

from langchain_core.documents import Document


class IngestionResult(TypedDict):
    project_name: str
    chunks: list[Document]
    chunk_count: int


class SourceEntry(TypedDict):
    chunk_id: str
    content_preview: str
    source: str | None


class QueryResult(TypedDict):
    answer: str
    sources: list[SourceEntry]

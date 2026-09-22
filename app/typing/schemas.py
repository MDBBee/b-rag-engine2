from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class IngestionSettings(BaseModel):
    chunk_size: int | None = Field(default=None)
    chunk_overlap: int | None = Field(default=None)
    oversized_threshold: int | None = Field(default=None)
    embedding_model: str | None = Field(default=None)


class RetrievalSettings(BaseModel):
    top_k: int | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    max_retries: int | None = Field(default=None)


class ChunkData(BaseModel):
    text: str
    types: list[str] = Field(default_factory=lambda: ["text"])
    tables: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)


class SummarizedChunk(BaseModel):
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    status: str
    chunk_count: int
    document_type: str
    no_of_pages: int = 0
    chunks: list[ChunkData] = Field(default_factory=list)
    summarized_chunks: list[SummarizedChunk] = Field(default_factory=list)
    detail: str | None = Field(default=None)


class QueryRequest(BaseModel):
    query: str
    collection_name: str
    top_k: int | None = Field(default=None)
    messages: list[dict] = Field(default_factory=list)
    retrieval_settings: RetrievalSettings | None = Field(default=None)


class SourceChunk(BaseModel):
    chunk_id: str
    content_preview: str
    source: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)


class CollectionInfo(BaseModel):
    collection_name: str
    chunk_count: int
    created_at: datetime


class CascadeDeleteResponse(BaseModel):
    deleted_vectors: int


class ChunkResponse(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionChunksResponse(BaseModel):
    collection_name: str
    chunk_count: int
    chunks: list[ChunkResponse] = Field(default_factory=list)

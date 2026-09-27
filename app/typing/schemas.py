from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


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
    llm_model: str | None = Field(default=None)
    project_name: str | None = Field(default=None)
    file_name: str | None = Field(default=None)


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

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
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    status: str
    chunk_count: int
    collection_name: str
    chunks: list[ChunkData] = Field(default_factory=list)
    detail: str | None = Field(default=None)


class ChatMessage(BaseModel):
    role: str
    content: str


class QueryRequest(BaseModel):
    query: str
    collection_name: str
    thread_id: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    messages: list[ChatMessage] = Field(default_factory=list)
    retrieval_settings: RetrievalSettings | None = Field(default=None)


class SourceChunk(BaseModel):
    chunk_id: str
    content_preview: str
    source: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)

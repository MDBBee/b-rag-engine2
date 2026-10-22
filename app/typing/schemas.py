from datetime import datetime
from typing import Any, Literal

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
    first_chunk_index: int = 0
    last_chunk_index: int = 0
    token_count: int = 0
    chunks: list[ChunkData] = Field(default_factory=list)
    summarized_chunks: list[SummarizedChunk] = Field(default_factory=list)
    detail: str | None = Field(default=None)


class ChatMessageHistory(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class QueryRequest(BaseModel):
    query: str
    project_name: str
    file_scope: list[str] | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    summary_chunks: int | None = Field(default=None, ge=10, le=1000)
    messages: list[ChatMessageHistory] = Field(default_factory=list)
    file_name: str | None = Field(default=None)
    max_retries: int | None = Field(default=None, ge=0, le=3)
    embedding_model: str | None = Field(default=None)


class SourceChunk(BaseModel):
    chunk_id: str
    content_preview: str
    source: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    model_used: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class DocumentInfo(BaseModel):
    name: str
    type: str
    chunk_count: int = 0
    uploaded_at: datetime | None = None


class CollectionInfo(BaseModel):
    project_name: str
    name: str | None = None
    documents: list[DocumentInfo] = Field(default_factory=list)
    chunk_count: int
    created_at: datetime


class CascadeDeleteResponse(BaseModel):
    deleted_vectors: int


class ChunkResponse(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CollectionChunksResponse(BaseModel):
    project_name: str
    chunk_count: int
    chunks: list[ChunkResponse] = Field(default_factory=list)


class QuizRequest(BaseModel):
    project_name: str
    file_scope: list[str] | None = Field(default=None)
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)


class QuizQuestion(BaseModel):
    question: str
    rich_content: str | None = Field(default=None, description="Optional markdown content (tables, mermaid diagrams) to display above the question")
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: Literal["A", "B", "C", "D"]


class RewordRequest(BaseModel):
    questions: list[QuizQuestion]


class QuizExplainRequest(BaseModel):
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    project_name: str
    llm_provider: str | None = Field(default=None)
    llm_model: str | None = Field(default=None)
    top_k: int | None = Field(default=None)
    messages: list[ChatMessageHistory] = Field(default_factory=list)


class CollectionUpdateRequest(BaseModel):
    name: str | None = None


class SummaryExportRequest(BaseModel):
    """Request to export a summary as PDF or Markdown."""
    markdown_text: str = Field(..., min_length=1)
    title: str = Field(default="Summary", max_length=200)

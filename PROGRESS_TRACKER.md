# Progress Tracker — b-rag-engine2

**Project:** Multimodal RAG System  
**Status:** Production Hardening Phase  
**Last Updated:** 2026-09-30

---

## Table of Contents

- [1. Current Status Summary](#1-current-status-summary)
- [2. Completed Phases](#2-completed-phases)
- [3. In Progress](#3-in-progress)
- [4. Next Steps](#4-next-steps)
- [5. Progress Log (Chronological)](#5-progress-log-chronological)
- [6. Database Schema](#6-database-schema)
- [7. API Endpoints](#7-api-endpoints)
- [8. Code Simplifications Applied](#8-code-simplifications-applied)

---

## 1. Current Status Summary

| Area | Status |
|------|--------|
| MongoDB Migration | ✅ Complete (all 12 phases) |
| JWT Authentication | ✅ Complete |
| Data Retrieval Endpoints | ✅ Complete |
| Ingestion Response Schema | ✅ Matches frontend |
| Stateless Queries | ✅ Removed checkpointing |
| Code Simplification | ✅ Complete |
| AWS Deployment | ✅ Complete (EC2 + Caddy + Cloudflare) |
| GitHub Actions CI/CD | ✅ Complete (OIDC + lint + terraform-plan + acceptance-test) |
| Rate Limiting | 🔄 Next |
| Production Tests | 🔄 Next |

---

## 2. Completed Phases

### ✅ Phase 1: MongoDB Atlas Setup
- MongoDB Atlas cluster created
- Database `b-rag` with collection: `vectors`
- Vector search index created programmatically
- Connection string configured in `.env`

### ✅ Phase 2: Dependencies
**Added:**
- `motor` — Async MongoDB driver
- `langchain-mongodb` — MongoDB vector store integration
- `python-jose[cryptography]` — JWT verification for auth
- `pymupdf` — PDF page count detection

**Removed:**
- `langchain-chroma` — ChromaDB integration
- `langgraph-checkpoint-sqlite` — SQLite checkpointer
- `chromadb` — ChromaDB client
- `aiosqlite` — Async SQLite driver
- `langgraph-checkpoint-mongodb` — No longer needed (stateless queries)

### ✅ Phase 3: Configuration
- Added `mongodb_uri` and `mongodb_database` settings
- Removed `chroma_persist_dir` and `sqlite_db_path`

### ✅ Phase 4: MongoDB Module
**File:** `app/utils/mongodb.py`

**Functions:**
- `init_mongodb()` — Initialize clients, LLM/embeddings, vectorstore, and ensure indexes
- `close_mongodb()` — Close connections
- `check_collection_exists()` — Uniqueness check
- `list_collections()` — List user's collections
- `delete_collection_cascade()` — Cascade delete
- `get_collection_chunks()` — Fetch all chunks for visualization

**Singleton Pattern:**
- Module-level variables: `client`, `db`, `vectors` (async)
- Shared instances: `llm`, `embeddings`, `vectorstore` (initialized once at startup)
- Direct access pattern: `mongodb.vectors.insert_many()`, `mongodb.llm.ainvoke()`

### ✅ Phase 5: Vector Store
**File:** `app/utils/mongodb.py`

- `vectorstore` singleton initialized at startup
- Uses `MongoDBAtlasVectorSearch` from `langchain-mongodb`
- Pre-filtering by `user_id` + `collection_name` at query time

### ✅ Phase 6: Ingestion Pipeline
**File:** `app/utils/ingestion_pipeline.py`

- `ingestion_pipeline(file_path, filename, collection_name, user_id)` — Main ingestion function
- Collection uniqueness check before ingestion
- Vectors stored with `user_id` + `collection_name`
- Document type detection from file extension
- PDF page count via PyMuPDF
- Returns: `(chunk_count, document_type, no_of_pages, chunks, summarized_chunks)`
- Blocking operations (markitdown, embeddings) wrapped in `asyncio.to_thread()`

### ✅ Phase 7: Retrieval Pipeline
**File:** `app/utils/retrieval_pipeline.py`

- `stream_query(query, collection_name, user_id)` — Streaming query
- Vector search filtered by `user_id` + `collection_name`
- Improved router prompt: explicitly classifies document-related vs general knowledge queries
- Improved generate prompt: prevents answering from general knowledge when context is irrelevant

### ✅ Phase 8: Schemas
**File:** `app/typing/schemas.py`

- `QueryRequest` — no `user_id` (comes from JWT)
- `ChunkData` — `text`, `types`, `tables`, `images` (matches frontend)
- `SummarizedChunk` — `page_content`, `metadata` (matches frontend)
- `IngestResponse` — `status`, `chunk_count`, `document_type`, `no_of_pages`, `chunks`, `summarized_chunks`, `detail`
- `CollectionInfo`, `CascadeDeleteResponse` — collection management
- `CollectionChunksResponse`, `ChunkResponse` — chunk retrieval

### ✅ Phase 9: Routers
**Files:** `app/routers/ingestion.py`, `app/routers/retrieval.py`, `app/routers/collections.py`

- All routers use `user: UserInfo = Depends(get_current_user)` for JWT auth
- `user_id` never passed in request body — always from JWT
- Ingestion: 409 on duplicate collection
- Collections: GET list, GET chunks, DELETE cascade

### ✅ Phase 10: Main App
**File:** `app/main.py`

- Lifespan context manager for MongoDB lifecycle (replaces deprecated `on_event`)
- Registered all routers: ingestion, retrieval, collections
- CORS middleware configured
- Global `HTTPException` handler for visible error logging

### ✅ Phase 11: Environment
**File:** `.env.example`

- `MONGODB_URI` and `MONGODB_DATABASE` placeholders
- `AUTH_SECRET` and `AUTH_ENABLED` placeholders
- Removed old ChromaDB/SQLite references

### ✅ Phase 12: Testing
**Test Results:**
- ✅ Ingestion: 184 chunks stored with user_id
- ✅ Collection uniqueness: 409 Conflict on duplicate
- ✅ Collection listing: returns collections with chunk counts
- ✅ Vector search: 5 documents found with pre-filtering
- ✅ Query/stream: sources + answer returned
- ✅ Delete collection: 184 vectors deleted

### ✅ Phase 13: Authentication
**Files:** `app/middleware/auth.py`, `app/config.py`

- JWT Bearer token authentication via `python-jose`
- `get_current_user` dependency extracts `UserInfo(id, email, role)` from token
- `require_admin` dependency for admin-only endpoints
- `AUTH_SECRET` setting (shared with frontend for JWT verification)
- `AUTH_ENABLED` setting for self-hosted bypass (returns mock admin user)
- All endpoints except `/health` require `Authorization: Bearer <jwt>`
- `user_id` removed from all request bodies — always from JWT

### ✅ Phase 14: Data Retrieval Endpoints
**Files:** `app/routers/collections.py`, `app/utils/mongodb.py`

- `GET /collections/{name}/chunks` — fetch all chunks for visualization page
- Enables data persistence after logout/re-login

### ✅ Phase 15: Ingestion Response Schema
**Files:** `app/typing/schemas.py`, `app/utils/ingestion_pipeline.py`

- Updated `IngestResponse` to match frontend schema
- Added `document_type` (detected from file extension)
- Added `no_of_pages` (PyMuPDF for PDFs, 0 for others)
- Updated `ChunkData` with `types`, `tables`, `images` arrays
- Added `SummarizedChunk` with `page_content` + `metadata.chunk_id`
- Frontend visualization page now works correctly

### ✅ Phase 16: AWS Deployment
**Date:** 2026-09-27

- EC2 instance (t3.micro) in dedicated VPC
- Caddy reverse proxy with auto SSL
- Cloudflare DNS + WAF + DDoS protection
- Security group restricted to Cloudflare IPs only
- SSM Parameter Store for secrets
- Docker network isolation (FastAPI internal only)

### ✅ Phase 17: GitHub Actions CI/CD
**Date:** 2026-09-29

- OIDC authentication (no IAM keys)
- 3 jobs: lint → terraform-plan (PRs only) → acceptance-test
- Path filters (only triggers on relevant file changes)
- Concurrency control (cancels in-progress runs)
- Automatic stale lock cleanup on failure/cancellation
- Branch protection rules (require lint + acceptance-test to pass)

---

## 3. In Progress

| Task | Status | Notes |
|------|--------|-------|
| Rate Limiting (slowapi) | 🔄 Planned | Per-endpoint limits |
| Production Tests | 🔄 Planned | pytest suite |
| Documentation Consolidation | 🔄 In Progress | 3-file structure |

---

## 4. Next Steps

### Phase 18: Production Features (Planned)

- [ ] Add rate limiting (slowapi)
- [ ] Add structured logging (structlog)
- [ ] Add error tracking (Sentry)
- [ ] Add comprehensive tests (pytest)
- [ ] Add input validation (file type checking, MIME verification)
- [ ] Add monitoring and metrics

---

## 5. Progress Log (Chronological)

### 2026-09-30 (CI/CD Improvements)
- ✅ Added `TF_INPUT: "false"` to prevent terraform hanging on missing variables
- ✅ Added `-lock-timeout=60s` to terraform plan command
- ✅ Changed cleanup condition to `failure() || cancelled()` for better lock handling
- ✅ Added `s3:DeleteObject` permission to OIDC role (manual IAM update)
- ✅ Added `ecr:DescribeRepositories`, `ecr:DescribeImages`, `ecr:ListTagsForResource` to OIDC role
- ✅ Updated AGENTS2.md with IAM permission documentation

### 2026-09-29 (GitHub Actions CI/CD)
- ✅ OIDC authentication setup (no IAM keys)
- ✅ Workflow: lint → terraform-plan → acceptance-test
- ✅ Immutable subject claims for OIDC trust policy
- ✅ Automatic stale lock cleanup
- ✅ Branch protection rules configured

### 2026-09-27 (AWS Deployment)
- ✅ Phase 0: S3 backend bucket + SSH key pair
- ✅ Phase 1: Terraform apply (VPC, EC2, ECR, IAM, SSM)
- ✅ Phase 2: SSM secrets configured
- ✅ Phase 3: DNS (Cloudflare + Namecheap + Vercel)
- ✅ Phase 4: Docker build & push to ECR
- ✅ Phase 5: Deploy containers (Caddy + FastAPI)
- ✅ Phase 6: Verify deployment
- ✅ Security hardening: Cloudflare IP whitelist
- ✅ CORS fix: Changed `allow_credentials=True` to `False`

### 2026-09-21 (Removed Checkpointing & Conversation Tracking)
- ✅ Removed `langgraph-checkpoint-mongodb` dependency
- ✅ Removed `conversations` collection and all tracking
- ✅ Removed `thread_id` handling from query pipeline
- ✅ Simplified `delete_collection_cascade()` to only delete vectors
- ✅ Simplified `RAGState` to use plain `query` string instead of message history
- ✅ Expected speedup: Conversational queries ~4-6s → ~2-3s (single LLM call)

### 2026-09-21 (Auth + Data Retrieval)
- ✅ JWT Bearer token authentication — `get_current_user` dependency extracts `user_id` from token
- ✅ `AUTH_SECRET` + `AUTH_ENABLED` settings for self-hosted bypass
- ✅ Global `HTTPException` handler for visible error logging
- ✅ Ingestion response updated to match frontend schema
- ✅ `GET /collections/{name}/chunks` — fetch all chunks for visualization page
- ✅ Added `pymupdf` for PDF page count detection

### 2026-09-20 (Event Loop Fix)
- ✅ Fixed blocking calls in ingestion pipeline — wrapped `MarkItDown.convert()` and `embed_documents()` in `asyncio.to_thread()` to prevent freezing the event loop
- ✅ Added logging for chunk count before embedding

### 2026-09-20 (Code Simplification & Bug Fixes)
- ✅ Removed `factories.py` — consolidated singletons into `mongodb.py`
- ✅ Removed `router_model` config — single LLM for routing and generation
- ✅ Fixed per-request `MongoClient` leak — now initialized once at startup
- ✅ Replaced deprecated `on_event` with lifespan context manager
- ✅ Fixed router prompt — explicitly classifies document-related vs general knowledge queries
- ✅ Fixed generate prompt — prevents answering from general knowledge when context is irrelevant

### 2026-09-20 (MongoDB Migration Complete)
- ✅ All 12 migration phases complete
- ✅ MongoDB Atlas vector storage with user isolation
- ✅ Collection uniqueness enforcement per user
- ✅ Cascade delete (vectors only — stateless queries)
- ✅ New `/collections` endpoints (GET/DELETE)
- ✅ Code simplifications applied
- ✅ All tests passing

### 2026-09-20 (FastAPI Integration)
- ✅ FastAPI app structure created
- ✅ Ingestion pipeline implemented
- ✅ Retrieval pipeline with streaming
- ✅ All endpoints tested

### 2026-09-19 (Prototype Phase)
- ✅ All 8 prototype segments complete
- ✅ Router pattern implemented
- ✅ Async streaming with token-by-token output
- ✅ Chunk deduplication for better retrieval

---

## 6. Database Schema

### Collection: `vectors`

```json
{
  "_id": "ObjectId",
  "user_id": "user-email-or-id",
  "collection_name": "thesis_masters",
  "chunk_index": 0,
  "content": "chunk text",
  "embedding": [0.1, 0.2, ...],
  "metadata": {
    "source": "thesis_masters.pdf",
    "chunk_index": 0,
    "total_chunks": 184,
    "H1": "Introduction",
    "H2": "Background"
  },
  "created_at": "2026-09-20T..."
}
```

**Indexes:**
- Compound index on `(user_id, collection_name)`
- Vector search index on `embedding` with filters for `user_id` and `collection_name`

---

## 7. API Endpoints

All endpoints except `/health` require `Authorization: Bearer <jwt>` header.

### POST /ingest
**Request:** `multipart/form-data`
```python
{
  "file": UploadFile,
  "collection_name": "my_doc"  # optional, auto-generated from filename
}
```

**Response:**
```json
{
  "status": "ok",
  "chunk_count": 184,
  "document_type": "pdf",
  "no_of_pages": 5,
  "chunks": [{"text": "...", "types": ["text"], "tables": [], "images": []}],
  "summarized_chunks": [{"page_content": "...", "metadata": {"chunk_id": "0", ...}}],
  "detail": null
}
```

**Error:** 409 Conflict if collection already exists for user

### POST /query/stream
**Request:** `application/json`
```json
{
  "query": "What is hydrothermal carbonization?",
  "collection_name": "thesis_masters"
}
```

**Response:** Server-Sent Events (SSE)
```
data: {"type": "sources", "sources": [{"chunk_id": "0", "content_preview": "...", "source": "thesis_masters.pdf"}]}
data: {"type": "token", "content": "Hydrothermal"}
data: {"type": "token", "content": " carbonization"}
data: {"type": "done"}
```

### GET /collections
**Response:**
```json
[
  {
    "collection_name": "thesis_masters",
    "chunk_count": 184,
    "created_at": "2026-09-20T..."
  }
]
```

### GET /collections/{name}/chunks
**Response:**
```json
{
  "collection_name": "thesis_masters",
  "chunk_count": 184,
  "chunks": [
    {"id": "objectid", "text": "...", "metadata": {"source": "file.pdf", "chunk_index": 0}}
  ]
}
```

**Error:** 404 if collection not found

### DELETE /collections/{name}
**Response:**
```json
{
  "deleted_vectors": 184
}
```

---

## 8. Code Simplifications Applied

### Removed Over-Engineering

1. **Removed getter functions** — Direct access to module-level variables
2. **Removed `factories.py`** — Consolidated into `mongodb.py` singletons
3. **Removed `router_model` config** — Single LLM instance for both routing and generation
4. **Removed per-request client creation** — Singletons initialized once at startup (fixes MongoClient leak)
5. **Replaced deprecated `on_event`** — Using lifespan context manager
6. **Re-added `asyncio.to_thread()`** — Blocking calls (markitdown, embeddings) must not freeze event loop
7. **Removed conversation memory** — Stateless queries, no checkpointing or conversation tracking
8. **Removed `langgraph-checkpoint-mongodb`** — No longer needed without checkpointing
9. **Removed `conversations` collection** — No conversation metadata tracking
10. **Removed conversation endpoints** — `GET /conversations` and `GET /conversations/{thread_id}/messages` deleted

### Current Patterns

**MongoDB Access:**
```python
from app.utils import mongodb

# Direct access to collections
await mongodb.vectors.insert_many(docs)
```

**LLM/Embeddings/Vectorstore:**
```python
from app.utils import mongodb

# Use shared singletons (initialized once at startup)
await mongodb.llm.ainvoke(messages)
await mongodb.llm.astream(messages)
embedding_vectors = await asyncio.to_thread(mongodb.embeddings.embed_documents, texts)
docs = await mongodb.vectorstore.asimilarity_search(query, k=5, pre_filter=filter)
```

**Ingestion Pipeline:**
```python
# Blocking operations wrapped in asyncio.to_thread() to avoid freezing event loop
md = MarkItDown()
result = await asyncio.to_thread(md.convert, file_path)

header_chunks = header_splitter.split_text(markdown_text)
embedding_vectors = await asyncio.to_thread(mongodb.embeddings.embed_documents, texts)

# Only MongoDB operations are async
await mongodb.vectors.insert_many(docs_to_insert)
```

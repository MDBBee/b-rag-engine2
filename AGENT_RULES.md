# Agent Rules — b-rag-engine2

**Strict rules for AI agents working on this project. Follow them exactly.**

---

## Table of Contents

- [1. Critical Warnings](#1-critical-warnings)
- [2. Tech Stack (Locked)](#2-tech-stack-locked)
- [3. Code Style & Conventions](#3-code-style--conventions)
- [4. File Structure Rules](#4-file-structure-rules)
- [5. What NOT To Do](#5-what-not-to-do)
- [6. Verification Checklist](#6-verification-checklist)
- [7. Context7 MCP Usage](#7-context7-mcp-usage)
- [8. Lessons Learned](#8-lessons-learned)

---

## 1. Critical Warnings

### AWS CLI Commands

**NEVER run AWS CLI commands without explicit user permission.**

- AWS resources cost money. Every API call (SSM, EC2, ECR, etc.) has a cost.
- You may edit, write, and delete files freely.
- You may NOT run `aws` CLI commands, `docker` commands against AWS, or any command that interacts with AWS services without asking the user first.
- This includes read-only commands like `aws ssm get-parameter` or `aws ec2 describe-instances`.
- When you need to verify AWS state, provide the command as a code block and ask the user to run it.

**Example:**
```bash
# Instead of running this yourself, ask the user:
aws ssm get-parameter --name "/brag/cors_origins" --region eu-north-1
```

### GitHub Actions & Terraform

- **DO NOT run CLI commands against AWS/GitHub resources** — always ask for permission first.
- **Research modern practices** — use Context7 for up-to-date syntax and patterns.
- **No over-engineering** — simple is always the best.
- **Ask before executing** — especially for deployments, infrastructure changes, or resource modifications.

---

## 2. Tech Stack (Locked)

**Use ONLY these tools:**

| Component | Choice | Version/Notes |
|-----------|--------|---------------|
| Document Conversion | markitdown | `markitdown[pdf,docx,pptx,xlsx]` — never use unstructured directly |
| Page Count | PyMuPDF (fitz) | PDF page count detection only |
| Orchestration | LangChain + LangGraph | langchain, langgraph, langchain-mongodb, langchain-openai |
| Vector Store | MongoDB Atlas | langchain-mongodb integration, persistent storage |
| Embeddings | OpenAI (via LangChain + OpenRouter) | `text-embedding-3-small` |
| LLM | OpenAI (via LangChain + OpenRouter) | `openai/gpt-4o-mini` |
| Chunking | Hybrid (Header + Recursive) | MarkdownHeaderTextSplitter → RecursiveCharacterTextSplitter |
| API Layer | FastAPI | `fastapi[standard]` (includes uvicorn) |
| API Provider | OpenRouter | Unified API, uses `OPENROUTER_API_KEY` |
| Authentication | python-jose | JWT verification (HS256) with shared `AUTH_SECRET` |

**Important:** All LLM and embedding calls go through LangChain (`ChatOpenAI`, `OpenAIEmbeddings`), configured with OpenRouter's base URL and API key. **No direct `openai` SDK usage.**

### Do NOT Add

- ❌ Other vector stores (Qdrant, Pinecone, Weaviate, ChromaDB)
- ❌ Other embedding providers (HuggingFace, Cohere, Google)
- ❌ Other LLM providers (Anthropic, Google, local models)
- ❌ Other document parsers (unstructured, docx2txt) — use markitdown
- ❌ Direct `openai` SDK calls (use LangChain wrappers instead)
- ❌ Conversation memory/checkpointing (queries are stateless)

---

## 3. Code Style & Conventions

### Code Style

**No over-engineering. Keep it modern and simple.**

- Write straightforward code — no unnecessary abstractions, classes, or wrappers
- Use modern Python (3.11+) features: type hints, f-strings, walrus operator where helpful
- Prefer built-in functions over custom implementations
- Keep functions short (< 20 lines when possible)
- One function = one responsibility
- No premature optimization
- No "just in case" code — only write what's needed NOW
- If a solution feels complex, simplify it

### FastAPI Structure

- All endpoints in `app/routers/`
- Business logic in `app/utils/`
- Auth middleware in `app/middleware/auth.py`
- Pydantic models in `app/typing/schemas.py`
- Configuration in `app/config.py`

### Python Style

- Use `uv run` never `python` directly
- Use `uv add <package>` never `pip install`
- Use type hints everywhere
- Keep functions simple and testable
- Use async/await for MongoDB operations (motor) and wrap blocking calls with `asyncio.to_thread()`
- Blocking operations (markitdown, embeddings) MUST use `asyncio.to_thread()` to avoid freezing the event loop

### Configuration

- All settings in `app/config.py` using `pydantic-settings`
- Load from `.env` file automatically
- Use `settings` singleton throughout the app
- CORS origins: comma-separated string in `.env`, parsed to list in config

### Authentication

- All endpoints except `/health` require `Authorization: Bearer <jwt>` header
- JWT is decoded with `python-jose` using shared `AUTH_SECRET` (matches frontend)
- `get_current_user` dependency extracts `UserInfo(id, email, role)` from token
- `user_id` is never passed in request body — always from JWT
- When `AUTH_ENABLED=false`, returns mock `UserInfo(id="local", email="admin@local", role="admin")`
- `require_admin` dependency checks `role == 'admin'`

### LangChain + OpenRouter Pattern

All LLM and embedding calls use LangChain wrappers configured with OpenRouter. Singletons are initialized once at startup in `mongodb.py`:

```python
from app.utils import mongodb

# Use shared singletons (initialized once at startup)
await mongodb.llm.ainvoke(messages)
await mongodb.llm.astream(messages)
embedding_vectors = mongodb.embeddings.embed_documents(texts)
docs = await mongodb.vectorstore.asimilarity_search(query, k=5, pre_filter=filter)
```

**Never use direct `openai` SDK calls.** Never create new LLM/embedding instances. Always use the shared singletons from `mongodb.py`.

### Async Patterns

- Pipeline functions are async only where needed (MongoDB operations via motor)
- Blocking operations (markitdown, text splitters, embeddings) MUST use `asyncio.to_thread()` to avoid freezing the event loop
- Use `await` for LangChain async methods (`ainvoke`, `astream`, `asimilarity_search`)
- Streaming responses use `astream_events(version="v2")`

### Stateless Queries

- Each query is independent — no conversation memory or checkpointing
- Frontend manages conversation history client-side if needed
- `thread_id` is ignored by the backend (kept in schema for backward compatibility)
- No MongoDB writes during query processing (only reads for vector search)

### MongoDB Patterns

- Use module-level variables (`client`, `db`, `vectors`) initialized in `init_mongodb()`
- If init fails, app fails — no fallback needed
- Access collections directly: `mongodb.vectors`
- No getter functions — direct variable access is simpler
- No sync client needed (no LangGraph checkpointer)

### markitdown Initialization

- **Basic mode** (default): `MarkItDown()` — for PDF, DOCX, PPTX, XLSX, HTML
- **Vision mode** (only for images): `MarkItDown(llm_client=client, llm_model="openai/gpt-4o")` — for JPG, PNG, etc.
- **Never pass LLM client for PDF processing** — GPT-4o doesn't accept PDF files directly
- Use basic mode for all document conversion
- Image descriptions are skipped (would require separate vision pipeline)

---

## 4. File Structure Rules

```
b-rag-engine2/
├── AGENT_RULES.md             # This file (instructions)
├── PROGRESS_TRACKER.md        # Activity log and phases
├── DEPLOYMENT_GUIDE.md        # Step-by-step deployment
├── README.md                  # GitHub display (professional)
├── proto.ipynb                # Prototype notebook (reference, not actively developed)
├── .env                       # API keys (gitignored, contains actual secrets)
├── .env.example               # API key template (committed, shows variable names)
├── .gitignore
├── pyproject.toml             # uv dependencies
├── uv.lock
├── data/                      # Sample documents for testing
│   └── (user uploads here)
└── app/                       # FastAPI application
    ├── __init__.py
    ├── main.py                # FastAPI app + CORS + lifespan + /health + exception handler
    ├── config.py              # Settings (env vars, pydantic-settings)
    ├── middleware/            # Auth middleware
    │   ├── __init__.py
    │   └── auth.py            # JWT auth: get_current_user, require_admin (AUTH_SECRET)
    ├── typing/                # Pydantic models + TypedDict
    │   ├── __init__.py
    │   ├── schemas.py         # Request/response models
    │   └── types.py           # Internal types
    ├── routers/               # API endpoints
    │   ├── __init__.py
    │   ├── ingestion.py       # POST /ingest
    │   ├── retrieval.py       # POST /query/stream
    │   └── collections.py     # GET/DELETE /collections, GET /collections/{name}/chunks
    └── utils/                 # Business logic
        ├── __init__.py
        ├── mongodb.py         # MongoDB client, singletons (llm, embeddings, vectorstore)
        ├── ingestion_pipeline.py  # Async ingestion pipeline
        └── retrieval_pipeline.py  # Async retrieval pipeline with LangGraph
```

**Rules:**
- All FastAPI development in `app/` directory
- `proto.ipynb` is reference only (do not add new features)
- Sample documents go in `data/`
- MongoDB Atlas stores vectors only (no conversation tracking)
- `.env.example` is committed to git (template with variable names)
- `.env` is gitignored (contains actual secrets, never commit)
- Use `OPENROUTER_API_KEY` for all API calls

---

## 5. What NOT To Do

### FastAPI Development

- ❌ Don't add features to `proto.ipynb` (it's reference only)
- ❌ Don't create instances of LLM/embeddings directly (use shared singletons from `mongodb.py`)
- ❌ Don't use other vector stores or embedding providers
- ❌ Don't over-engineer (no complex abstractions)
- ❌ Don't modify files outside `b-rag-engine2/`
- ❌ Don't skip phases in PROGRESS_TRACKER.md
- ❌ Don't continue to next phase without testing the current one
- ❌ Don't pass `user_id` in request body — always use JWT via `get_current_user` dependency

### General

- ❌ Don't use `pip` — always use `uv`
- ❌ Don't commit `.env`
- ❌ Don't hardcode API keys in code
- ❌ Don't use `print()` in production code (use `logging`)
- ❌ Don't use direct `openai` SDK calls — always use LangChain's `ChatOpenAI` and `OpenAIEmbeddings`
- ❌ Don't create new LLM/embeddings instances in each function (use shared singletons from `mongodb.py`)
- ❌ Don't use PyMuPDF for document conversion — use markitdown (PyMuPDF is only for page count)
- ❌ Don't add conversation memory or checkpointing — queries are stateless

---

## 6. Verification Checklist

**Before moving to next phase, verify:**

### Authentication

- [ ] Bearer token required on all endpoints except `/health`
- [ ] Invalid token returns 401
- [ ] Expired token returns 401 with "Token expired"
- [ ] Missing `AUTH_SECRET` returns 500 with clear error
- [ ] `AUTH_ENABLED=false` bypasses auth (returns mock admin)

### Ingestion Endpoint (`POST /ingest`)

- [ ] File upload works (PDF, DOCX, etc.)
- [ ] File size limit enforced (50MB)
- [ ] Collection name auto-generated from filename if not provided
- [ ] Document converted to markdown
- [ ] Hybrid chunking works (header + recursive)
- [ ] Chunks stored in MongoDB Atlas
- [ ] 409 Conflict on duplicate collection for same user
- [ ] Response includes `document_type`, `no_of_pages`, `chunks`, `summarized_chunks`

### Retrieval Endpoint (`POST /query/stream`)

- [ ] Streaming response works (SSE)
- [ ] Router classifies query intent correctly
- [ ] Document queries retrieve from vector store
- [ ] Conversational queries answer directly (no retrieval)
- [ ] Sources returned with chunk_id, content_preview, source
- [ ] System prompts enforce document-focused assistance
- [ ] Off-topic questions politely declined

### Data Retrieval Endpoints

- [ ] `GET /collections/{name}/chunks` returns all chunks for visualization
- [ ] All endpoints filtered by `user_id` from JWT

### Configuration

- [ ] All settings loaded from `.env`
- [ ] CORS origins parsed correctly (comma-separated)
- [ ] MongoDB URI configured
- [ ] OpenRouter API key validated
- [ ] AUTH_SECRET configured (matches frontend)

---

## 7. Context7 MCP Usage

**Before implementing any feature, use Context7 MCP to retrieve modern, up-to-date documentation.**

### When to Use Context7

- **Before writing code** — Look up the latest API for the library you're using
- **When unsure about syntax** — Don't guess, check the docs
- **When implementing a feature** — Verify the current best practice
- **When encountering errors** — Check if the API has changed
- **Before MongoDB migration** — Look up MongoDB Atlas Vector Search

### How to Use Context7

1. **Resolve library ID** — Find the correct Context7-compatible library ID
   ```
   context7_resolve-library-id(libraryName="FastAPI", query="file upload endpoint")
   ```
2. **Query documentation** — Get specific code examples and API usage
   ```
   context7_query-docs(libraryId="/tiangolo/fastapi", query="handle file upload with form data")
   ```

### Libraries to Query

| Library | Context7 ID | When to Query |
|---------|-------------|---------------|
| markitdown | `/microsoft/markitdown` | Document conversion |
| LangChain | `/websites/langchain_oss_python_langchain` | Chunking, retrieval, RAG |
| langchain-mongodb | Check via resolve | Vector store operations |
| langchain-openai | Check via resolve | Embeddings, LLM |
| FastAPI | `/tiangolo/fastapi` | Endpoints, file uploads, streaming |
| LangGraph | `/websites/langchain_oss_python_langgraph` | StateGraph, streaming |
| MongoDB | `/mongodb/docs` | MongoDB Atlas Vector Search |
| python-jose | Check via resolve | JWT decode/verify |

### Example Workflow

```
Implementing file upload endpoint:
1. context7_resolve-library-id(libraryName="FastAPI", query="file upload")
2. context7_query-docs(libraryId="/tiangolo/fastapi", query="UploadFile with form data")
3. Read the returned code examples
4. Implement using the LATEST API (not outdated patterns)
```

**Why Context7?**
- Training data may be outdated
- APIs change frequently (LangChain, FastAPI especially)
- Context7 provides current, version-specific documentation
- Prevents using deprecated methods

---

## 8. Lessons Learned

### OIDC Setup Pitfalls

1. **Immutable Subject Claims** — GitHub introduced immutable subject claims for repositories created after July 15, 2026, or that opt in. The subject claim includes `@ORG_ID` and `@REPO_ID` suffixes. Always check your repository's OIDC settings to determine which format to use.

2. **No Spaces in Subject** — The subject claim must not contain spaces. Common mistake: `repo:MDBBee/ b-rag-engine2` (space after slash).

3. **Wildcard for Flexibility** — Using `StringLike` with `*` wildcard allows the role to be assumed from any branch or PR, which is more flexible than listing specific branches.

4. **Thumbprint Not Required** — As of July 2023, AWS validates GitHub's OIDC provider using trusted root CAs automatically. The thumbprint is only a fallback and is essentially ignored.

5. **IAM Propagation Delay** — After creating or updating IAM roles/policies, wait 2-5 minutes for changes to propagate globally before testing.

### Action Version Management

1. **Verify from Official Sources** — Always check the actual GitHub releases page for the latest version, not documentation or blog posts which may be outdated.

2. **Use Specific Versions** — Pin to specific versions (e.g., `@v7.0.1`) rather than major versions (e.g., `@v7`) for reproducibility.

3. **Update Regularly** — GitHub Actions deprecate old Node.js versions. Keep actions updated to avoid runtime errors.

### Terraform State Lock Management

1. **Stale Locks from Cancelled Workflows** — When a workflow is cancelled or crashes, it may leave a stale lock in S3. Always include automatic cleanup steps in the workflow to handle this.

2. **Force-Unlock is Safe** — Using `terraform force-unlock` with a specific lock ID is safe when you know the lock is stale. The lock file contains all the information needed to identify it.

3. **Concurrency Control is Essential** — Use GitHub Actions `concurrency` settings to prevent parallel runs that could cause lock conflicts.

4. **Automatic Cleanup on Failure or Cancellation** — Add cleanup steps that run `if: failure() || cancelled()` to automatically release locks when terraform commands fail or are cancelled.

5. **Lock Info File Location** — The lock info is stored in `.terraform/terraform.tfstate.lock.info` and can be parsed with `jq` to extract the lock ID for automatic cleanup.

### Terraform Variables in CI

1. **Variables Without Defaults Hang CI** — Terraform variables without default values cause Terraform to wait for interactive input. In CI (non-interactive mode), this input never comes, so Terraform hangs indefinitely.

2. **Use TF_VAR_* for CI** — Provide dummy values via `TF_VAR_*` environment variables for `terraform plan`. This is the cleanest approach and doesn't require changes to terraform files.

3. **Use TF_INPUT=false** — Set `TF_INPUT: "false"` to prevent terraform from prompting for input. If variables are missing, it will error immediately instead of hanging.

4. **Use -lock-timeout** — Add `-lock-timeout=60s` to terraform plan to prevent indefinite hangs on lock acquisition.

5. **Dummy Values are Safe for Plan** — `terraform plan` only reads state and shows what would change. It doesn't actually create or modify resources, so dummy values don't matter.

6. **Real Values Needed for Apply** — When running `terraform apply` manually (locally), you need real values for variables like `api_domain` and `your_ip`. Provide these via `terraform.tfvars` or `-var` flags.

### IAM Permissions for OIDC Role

1. **S3 DeleteObject Required** — The OIDC role needs `s3:DeleteObject` to release state locks. Without it, terraform creates `.tflock` files but can't delete them after plan/apply, causing stale locks that block subsequent runs.

2. **ECR Read Permissions Required** — Terraform reads all attributes of resources it manages during `terraform plan`. If you have ECR resources, the role needs `ecr:DescribeRepositories`, `ecr:DescribeImages`, and `ecr:ListTagsForResource`.

3. **Symptoms of Missing Permissions** — Errors like `AccessDeniedException: User is not authorized to perform: ecr:ListTagsForResource` or `failed to delete the lock file: AccessDenied` indicate missing IAM permissions.

4. **Terraform Reads Everything** — Even for read-only operations like `terraform plan`, terraform must read all resource attributes to detect drift. This includes tags, metadata, and related resources.

---

## Questions?

If anything is unclear:
1. Stop and ask the user
2. Don't make assumptions
3. Don't deviate from the plan without approval

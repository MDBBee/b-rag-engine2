# b-rag-engine2

Production-grade FastAPI backend for a multimodal Retrieval-Augmented Generation (RAG) system with MongoDB Atlas vector storage, JWT authentication, and agentic retrieval workflows powered by LangGraph.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Vercel)                        │
│                    brag.bobbyugbebor.store                       │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ Bearer Token + JSON
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Cloudflare (WAF + DDoS)                     │
│                 api-brag.bobbyugbebor.store                      │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ HTTPS (Cloudflare IPs only)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AWS EC2 (eu-north-1)                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Security Group (Restricted)                   │  │
│  │  • Port 443: Cloudflare IPs only                          │  │
│  │  • Port 80: Cloudflare IPs only                           │  │
│  │  • Port 22: Admin IP only                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│  ┌───────────────────────────▼───────────────────────────────┐  │
│  │              Docker Network (brag-net)                     │  │
│  │  ┌─────────────────┐         ┌─────────────────────────┐  │  │
│  │  │  Caddy (:443)   │────────▶│  FastAPI (:8000)        │  │  │
│  │  │  Reverse Proxy  │         │  Internal Only          │  │  │
│  │  │  Auto SSL       │         │  Not exposed to internet│  │  │
│  │  └─────────────────┘         └─────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ Vector Search
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MongoDB Atlas                                 │
│              Collection: vectors (with embeddings)               │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component               | Technology                    |
| ----------------------- | ----------------------------- |
| **Framework**           | FastAPI                       |
| **Vector Store**        | MongoDB Atlas                 |
| **Embeddings**          | OpenAI text-embedding-3-small |
| **LLM**                 | OpenAI gpt-4o-mini            |
| **Orchestration**       | LangChain + LangGraph         |
| **Document Processing** | markitdown                    |
| **Authentication**      | python-jose (JWT HS256)       |
| **Reverse Proxy**       | Caddy                         |
| **Containerization**    | Docker                        |

## Key Features

- **Multimodal Document Processing**: Converts PDF, DOCX, PPTX, XLSX, and HTML to markdown with hybrid chunking strategy
- **Multi-Tenant Architecture**: MongoDB Atlas vector search with user isolation via `user_id` filtering and collection-level access control
- **Agentic Retrieval**: LangGraph workflow with intent routing, intelligent query classification, and retry logic for improved retrieval accuracy
- **Streaming Responses**: Server-Sent Events (SSE) for real-time token streaming with source attribution
- **Cross-Domain JWT Auth**: Shared secret authentication with frontend, rate limiting support, and CORS configuration
- **Production Ready**: Dockerized with multi-stage builds, automated CI/CD pipeline, and acceptance testing

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- MongoDB Atlas connection string
- OpenRouter API key

### Setup

```bash
# Clone and install
git clone <repo-url>
cd b-rag-engine2
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Run development server
uv run fastapi dev app/main.py
```

Server runs on `http://localhost:8000` with hot reload. Full API documentation available at `/docs`.

## CI/CD Pipeline

Automated workflow on every push to `main` and pull requests:

1. **Linting**: `ruff` code quality checks
2. **Terraform Validation**: Infrastructure plan review with PR comments
3. **Acceptance Testing**: Robot Framework integration tests with full stack deployment
4. **Artifact Management**: Test results preserved for debugging

The acceptance test suite validates end-to-end functionality including document ingestion, vector storage, and query retrieval with automated test data.

## Production Deployment

Deployed to AWS EC2 (t3.micro, Amazon Linux 2023) with the following infrastructure:

- **VPC**: Dedicated virtual network with public subnet
- **Security Groups**: Ports 80/443 restricted to Cloudflare IPs only
- **ECR**: Docker image registry with automated builds
- **SSM Parameter Store**: Secrets management with encryption at rest
- **IAM Role**: Least-privilege access (ECR pull + SSM read only)
- **Cloudflare**: WAF + DDoS protection, DNS proxy, auto SSL

The FastAPI container runs on an internal Docker network, not directly exposed to the internet. Caddy handles TLS termination and reverse proxy duties.

## Configuration

Environment variables (see `.env.example`):

| Variable              | Description                                    | Required |
| --------------------- | ---------------------------------------------- | -------- |
| `OPENROUTER_API_KEY`  | OpenRouter API key                             | Yes      |
| `MONGODB_URI`         | MongoDB Atlas connection string                | Yes      |
| `AUTH_SECRET`         | Shared JWT secret (must match frontend)        | Yes      |
| `CORS_ORIGINS`        | Comma-separated allowed origins                | Yes      |
| `MONGODB_DATABASE`    | Database name (default:`b-rag`)                | No       |
| `AUTH_ENABLED`        | Enable/disable authentication (default:`true`) | No       |
| `OPENROUTER_BASE_URL` | OpenRouter API base URL                        | No       |
| `EMBEDDING_MODEL`     | Embedding model name                           | No       |
| `LLM_MODEL`           | LLM model name                                 | No       |
| `CHUNK_SIZE`          | Document chunk size                            | No       |
| `CHUNK_OVERLAP`       | Chunk overlap                                  | No       |
| `TOP_K`               | Number of chunks to retrieve                   | No       |

## License

Private project — not for distribution.

# b-rag-engine2

Production-ready FastAPI backend for a multimodal RAG (Retrieval-Augmented Generation) system with MongoDB Atlas vector storage, JWT authentication, and agentic retrieval workflows.

## Overview

This service provides document ingestion, vector storage, and intelligent query retrieval using LangChain and LangGraph. It's designed for multi-tenant applications with user isolation and secure authentication.

### Key Features

- **Document Ingestion**: Convert PDF, DOCX, PPTX, XLSX, HTML to markdown and chunk with hybrid strategy (header + recursive)
- **Vector Storage**: MongoDB Atlas with vector search, user isolation via `user_id` filtering
- **Agentic Retrieval**: LangGraph-based workflow with intent routing and streaming responses
- **Authentication**: JWT Bearer token verification (shared secret with frontend)
- **Multi-tenant**: Collection uniqueness per user, cascade delete support
- **Production Ready**: Dockerized, CORS configured, rate limiting support

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

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Framework** | FastAPI | Async API with automatic OpenAPI docs |
| **Vector Store** | MongoDB Atlas | Vector search with user isolation |
| **Embeddings** | OpenAI text-embedding-3-small | Via OpenRouter API |
| **LLM** | OpenAI gpt-4o-mini | Via OpenRouter API |
| **Orchestration** | LangChain + LangGraph | RAG pipeline and agentic workflows |
| **Document Processing** | markitdown | Convert PDF/DOCX/PPTX/XLSX/HTML to markdown |
| **Authentication** | python-jose | JWT verification (HS256) |
| **Reverse Proxy** | Caddy | Auto SSL, reverse proxy to FastAPI |
| **Containerization** | Docker | Multi-stage build, non-root user |

## API Endpoints

All endpoints except `/health` require `Authorization: Bearer <jwt>` header.

### Health Check
```
GET /health
```
Returns: `{"status": "ok"}`

### Document Ingestion
```
POST /ingest
Content-Type: multipart/form-data

Parameters:
- file: UploadFile (PDF, DOCX, PPTX, XLSX, HTML)
- collection_name: string (optional, auto-generated from filename)

Response:
{
  "status": "ok",
  "chunk_count": 184,
  "document_type": "pdf",
  "no_of_pages": 5,
  "chunks": [...],
  "summarized_chunks": [...]
}
```

### Query with Streaming
```
POST /query/stream
Content-Type: application/json

{
  "query": "What is hydrothermal carbonization?",
  "collection_name": "thesis_masters"
}

Response: Server-Sent Events (SSE)
data: {"type": "sources", "sources": [...]}
data: {"type": "token", "content": "Hydrothermal"}
data: {"type": "token", "content": " carbonization"}
data: {"type": "done"}
```

### List Collections
```
GET /collections

Response:
[
  {
    "collection_name": "thesis_masters",
    "chunk_count": 184,
    "created_at": "2026-09-20T..."
  }
]
```

### Get Collection Chunks
```
GET /collections/{name}/chunks

Response:
{
  "collection_name": "thesis_masters",
  "chunk_count": 184,
  "chunks": [...]
}
```

### Delete Collection
```
DELETE /collections/{name}

Response:
{
  "deleted_vectors": 184
}
```

## Local Development

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- MongoDB Atlas connection string
- OpenRouter API key

### Setup

```bash
# Clone repository
git clone <repo-url>
cd b-rag-engine2

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials:
# - OPENROUTER_API_KEY
# - MONGODB_URI
# - AUTH_SECRET (shared with frontend)
# - CORS_ORIGINS (comma-separated)

# Run development server
uv run fastapi dev app/main.py
```

Server runs on `http://localhost:8000` with hot reload.

### Testing

```bash
# Test health endpoint
curl http://localhost:8000/health

# Test with Swagger UI
open http://localhost:8000/docs
```

## Docker

### Build Production Image

```bash
docker build -t b-rag-engine2:latest --target prod .
```

### Run Container

```bash
docker run -d \
  --name brag-api \
  -p 8000:8000 \
  -e OPENROUTER_API_KEY="your-key" \
  -e MONGODB_URI="your-mongodb-uri" \
  -e AUTH_SECRET="your-secret" \
  -e CORS_ORIGINS="http://localhost:3000,https://your-domain.com" \
  b-rag-engine2:latest
```

### Docker Compose (Development)

```bash
# Build frontend image first (if not done)
docker build -t b-rag-view:1.0.0 --target production ../b-rag-view

# Run with watch-sync
docker compose up --watch
```

## Deployment

### AWS Infrastructure

The production deployment uses:

- **EC2 Instance**: t3.micro (Amazon Linux 2023)
- **VPC**: Dedicated VPC with public subnet
- **Security Group**: Ports 80/443 restricted to Cloudflare IPs only
- **ECR**: Docker image registry
- **SSM Parameter Store**: Secrets management (encrypted at rest)
- **IAM Role**: Least-privilege (ECR pull + SSM read only)

### Security Layers

1. **Cloudflare**: WAF + DDoS protection, DNS proxy (hides real IP)
2. **Security Group**: Only Cloudflare IPs can reach ports 80/443
3. **Docker Network**: FastAPI container internal-only, not exposed to internet
4. **Caddy**: Auto SSL with Let's Encrypt, reverse proxy
5. **JWT Auth**: All endpoints require valid Bearer token
6. **CORS**: Browser enforces allowed origins

### Deployment Process

```bash
# 1. Build and push to ECR
docker build -t b-rag-engine2:latest --target prod .
docker tag b-rag-engine2:latest $ECR_URL:latest
docker push $ECR_URL:latest

# 2. SSH to EC2 and pull new image
ssh -i ~/.ssh/brag-key ec2-user@<EC2_IP>
aws ecr get-login-password --region eu-north-1 | docker login --username AWS --password-stdin $ECR_URL
docker pull $ECR_URL:latest

# 3. Fetch secrets from SSM
export OPENROUTER_API_KEY=$(aws ssm get-parameter --name /brag/openrouter_api_key --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export MONGODB_URI=$(aws ssm get-parameter --name /brag/mongodb_uri --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export AUTH_SECRET=$(aws ssm get-parameter --name /brag/auth_secret --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export CORS_ORIGINS=$(aws ssm get-parameter --name /brag/cors_origins --query 'Parameter.Value' --output text --region eu-north-1)

# 4. Restart container
docker stop brag-api && docker rm brag-api
docker run -d \
  --name brag-api \
  --network brag-net \
  --restart unless-stopped \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e MONGODB_URI="$MONGODB_URI" \
  -e AUTH_SECRET="$AUTH_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  $ECR_URL:latest
```

## Configuration

Environment variables (see `.env.example`):

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM and embeddings | Yes |
| `MONGODB_URI` | MongoDB Atlas connection string | Yes |
| `MONGODB_DATABASE` | Database name (default: `b-rag`) | No |
| `AUTH_SECRET` | Shared JWT secret (must match frontend) | Yes |
| `AUTH_ENABLED` | Enable/disable authentication (default: `true`) | No |
| `CORS_ORIGINS` | Comma-separated allowed origins | Yes |
| `OPENROUTER_BASE_URL` | OpenRouter API base URL | No |
| `EMBEDDING_MODEL` | Embedding model name | No |
| `LLM_MODEL` | LLM model name | No |
| `CHUNK_SIZE` | Chunk size for document splitting | No |
| `CHUNK_OVERLAP` | Chunk overlap for document splitting | No |
| `TOP_K` | Number of chunks to retrieve | No |

## Project Structure

```
b-rag-engine2/
├── app/
│   ├── main.py                 # FastAPI app, CORS, lifespan, exception handler
│   ├── config.py               # Settings (pydantic-settings)
│   ├── middleware/
│   │   └── auth.py             # JWT authentication
│   ├── routers/
│   │   ├── ingestion.py        # POST /ingest
│   │   ├── retrieval.py        # POST /query/stream
│   │   └── collections.py      # GET/DELETE /collections
│   ├── typing/
│   │   ├── schemas.py          # Pydantic models
│   │   └── types.py            # TypedDict definitions
│   └── utils/
│       ├── mongodb.py          # MongoDB client, singletons
│       ├── ingestion_pipeline.py
│       └── retrieval_pipeline.py
├── terraform/                  # Infrastructure as Code
│   ├── main.tf                 # Provider + backend
│   ├── vpc.tf                  # VPC, subnet, IGW
│   ├── security.tf             # Security group
│   ├── ec2.tf                  # EC2 instance
│   ├── ecr.tf                  # ECR repository
│   ├── iam.tf                  # IAM role + policies
│   ├── ssm.tf                  # SSM parameters
│   └── outputs.tf              # Terraform outputs
├── Dockerfile                  # Multi-stage build
├── docker-compose.yml          # Development setup
├── pyproject.toml              # Dependencies (uv)
└── .env.example                # Environment template
```

## Security Considerations

- **Never commit `.env`** — contains API keys and secrets
- **Never commit `terraform.tfvars`** — contains your IP address
- **Rotate secrets regularly** — OpenRouter API key, MongoDB URI, AUTH_SECRET
- **Restrict CORS origins** — only allow trusted frontend domains
- **Use Cloudflare proxy** — hides real EC2 IP, provides WAF/DDoS protection
- **Keep dependencies updated** — run `uv sync` regularly

## Troubleshooting

### CORS Errors

Check that:
1. `CORS_ORIGINS` in SSM includes your frontend domain
2. Container was restarted after updating SSM parameter
3. Verify with: `docker exec brag-api env | grep CORS`

### Authentication Failures

Check that:
1. `AUTH_SECRET` matches between frontend and backend
2. JWT token is not expired
3. Token is sent as `Authorization: Bearer <token>`

### Container Not Starting

Check logs:
```bash
docker logs brag-api
```

Common issues:
- Missing environment variables
- MongoDB connection failure
- Invalid API keys

## License

Private project — not for distribution.

## Author

Bobby Ugbebor

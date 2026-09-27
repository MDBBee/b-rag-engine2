# Docker Setup for b-rag-engine2

## Overview

Production-ready Docker image optimized for size and security.

**Final image size**: ~1.4-1.5 GB (down from 1.88 GB after optimization)

## Architecture

### Multi-stage build
- **Builder stage**: `python:3.11-slim` + `uv` for dependency installation
- **Runtime stage**: Clean `python:3.11-slim` with only the virtual environment and app code
- **Non-root user**: Runs as `app` user (security best practice)

### Base image choice
- `python:3.11-slim` (~120 MB) — Debian-based, well-supported, no build tools in runtime
- Alpine was considered but rejected: Python builds 50× slower on Alpine, and some packages (cryptography, numpy) need compilation

## Optimization Decisions

### Removed dependencies (saves ~360-500 MB)

#### 1. `ipykernel` — Removed
- **Reason**: Jupyter kernel, not used in production
- **Impact**: ~50-80 MB (ipykernel + ipython + jupyter-client + tornado + debugpy + pyzmq)
- **Note**: If you need Jupyter for development, move to `[dependency-groups] dev` instead

#### 2. `langchain-community` — Removed
- **Reason**: Not imported anywhere in `app/`
- **Impact**: ~10-20 MB
- **Note**: Package is being sunset by LangChain (archived Jun 2026)

#### 3. `markitdown[all]` → `markitdown[pdf,docx,pptx,xlsx]`
- **Reason**: `[all]` pulls in unused extras (audio, Outlook, YouTube, Azure SDKs, pandas/numpy)
- **Impact**: ~300-400 MB
- **What's included**: PDF, DOCX, PPTX, XLSX (modern Excel)
- **What's excluded**:
  - `audio-transcription` (pydub, speechrecognition)
  - `outlook` (olefile)
  - `youtube-transcription` (youtube-transcript-api)
  - `az-content-understanding` + `az-doc-intel` (Azure SDKs, ~100+ MB)
  - `xls` (old Excel format, requires pandas/numpy ~200 MB)

**If you need legacy .xls support**, change to `markitdown[pdf,docx,pptx,xlsx,xls]` (adds ~200 MB for pandas/numpy).

## Build & Run

### Build the image
```bash
docker build -t b-rag-engine2 .
```

### Run with environment variables
```bash
docker run -p 8000:8000 --env-file .env b-rag-engine2
```

### Run with individual env vars
```bash
docker run -p 8000:8000 \
  -e OPENROUTER_API_KEY=your_key \
  -e MONGODB_URI=mongodb+srv://... \
  -e AUTH_SECRET=your_secret \
  b-rag-engine2
```

### Run in detached mode
```bash
docker run -d -p 8000:8000 --env-file .env --name b-rag-engine2 b-rag-engine2
```

### Check logs
```bash
docker logs b-rag-engine2
docker logs -f b-rag-engine2  # follow
```

### Stop the container
```bash
docker stop b-rag-engine2
docker rm b-rag-engine2
```

## Image size breakdown

| Component | Size |
|-----------|------|
| `python:3.11-slim` base | ~120 MB |
| LangChain ecosystem (langchain, langgraph, langchain-openai, langchain-mongodb) | ~400-500 MB |
| OpenAI SDK + motor (MongoDB async driver) | ~50-100 MB |
| markitdown + pymupdf + core deps | ~150-200 MB |
| FastAPI + uvicorn + pydantic | ~50-100 MB |
| App code | < 1 MB |
| **Total** | **~1.4-1.5 GB** |

## Security

- **Non-root user**: Container runs as `app` user (UID assigned by `useradd`)
- **No `.env` in image**: Secrets injected at runtime via `--env-file` or `-e`
- **Minimal attack surface**: No build tools, no pip, no shell utilities in runtime stage
- **`.dockerignore`**: Excludes `.env`, `.git`, `__pycache__`, `.venv`, dev files

## Development vs Production

### Development (local)
```bash
uv run fastapi dev app/main.py
```
Hot reload on port 8000.

### Production (Docker)
```bash
docker build -t b-rag-engine2 .
docker run -p 8000:8000 --env-file .env b-rag-engine2
```
Runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` (no hot reload).

## Troubleshooting

### Image too large?
- Check if you added heavy dependencies back
- Run `docker history b-rag-engine2` to see layer sizes
- Consider removing unused markitdown extras (e.g., if you only need PDF, use `markitdown[pdf]`)

### Build fails?
- Ensure `uv.lock` is up to date: `uv lock`
- Check that all dependencies in `pyproject.toml` are compatible with Python 3.11

### Runtime errors?
- Verify all required env vars are set (see `.env.example`)
- Check MongoDB connection: `MONGODB_URI` must be valid
- Check logs: `docker logs <container_name>`

## Future optimizations

If you need to reduce size further:

1. **Use distroless images**: `gcr.io/distroless/python3` (~50 MB base, no shell)
2. **SlimToolKit**: Analyze runtime usage and strip unused files
3. **Strip `.pyc` files**: Add `find /app -name "*.pyc" -delete` in runtime stage
4. **Remove pip from runtime**: Already done via multi-stage build

**Note**: These add complexity. Current setup balances size, maintainability, and debuggability.

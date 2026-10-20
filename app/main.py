import logging
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import (
    collections,
    file_processing,
    ingestion,
    quiz,
    retrieval,
    summaries,
    youtube_ingest,
)
from app.utils.mongodb import close_mongodb, init_mongodb
from app.utils.retrieval_pipeline import init_graph

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.auth_secret:
        raise RuntimeError("AUTH_SECRET is required but not configured")
    await init_mongodb()
    init_graph()
    yield
    await close_mongodb()


app = FastAPI(title="b-rag-engine2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.middleware("http")
async def log_request_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s → %d (%.0fms)", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP {exc.status_code} {request.method} {request.url.path}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.include_router(ingestion.router)
app.include_router(youtube_ingest.router)
app.include_router(retrieval.router)
app.include_router(collections.router)
app.include_router(file_processing.router)
app.include_router(quiz.router)
app.include_router(summaries.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

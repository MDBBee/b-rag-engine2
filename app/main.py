from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import collections, file_processing, ingestion, retrieval
from app.utils.mongodb import close_mongodb, init_mongodb
from app.utils.retrieval_pipeline import init_graph

load_dotenv()
logging.basicConfig(
    level=logging.WARNING,
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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP {exc.status_code} {request.method} {request.url.path}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.include_router(ingestion.router)
app.include_router(retrieval.router)
app.include_router(collections.router)
app.include_router(file_processing.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

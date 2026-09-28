import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import ingestion, retrieval, collections
from app.utils.mongodb import init_mongodb, close_mongodb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_mongodb()
    yield
    await close_mongodb()


app = FastAPI(title="b-rag-engine2", version="0.1.0", lifespan=lifespan)

logger.info(f"CORS origins configured: {settings.cors_origins_list}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.middleware("http")
async def log_cors_debug(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin:
        logger.info(f"Request from origin: {origin}, path: {request.url.path}")
    response = await call_next(request)
    if origin:
        cors_header = response.headers.get("access-control-allow-origin")
        logger.info(f"CORS response for {origin}: allow-origin={cors_header}")
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP {exc.status_code} {request.method} {request.url.path}: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.include_router(ingestion.router)
app.include_router(retrieval.router)
app.include_router(collections.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

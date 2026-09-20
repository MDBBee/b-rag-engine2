import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ingestion, retrieval, collections
from app.utils.mongodb import init_mongodb, close_mongodb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_mongodb()
    yield
    await close_mongodb()


app = FastAPI(title="b-rag-engine2", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(ingestion.router)
app.include_router(retrieval.router)
app.include_router(collections.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

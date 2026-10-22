import logging
from datetime import UTC, datetime
from typing import TypedDict

from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MongoDB Schema
# ---------------------------------------------------------------------------
# Two collections, both multi-tenant (scoped by user_id):
#
# "vectors" — Vector chunks for RAG
#   Each document is one text chunk with its embedding vector.
#   Tenant isolation enforced by pre_filter in asimilarity_search().
#
# "projects" — Project metadata (one doc per project, not per chunk)
#   Used for listing projects, existence checks, and deletion cascades.
#   Avoids expensive aggregations on the vectors collection.
# ---------------------------------------------------------------------------

class DocumentInfo(TypedDict):
    """Schema for document metadata."""
    name: str
    type: str
    chunk_count: int
    uploaded_at: datetime

class VectorDocument(TypedDict):
    """Schema for documents in the 'vectors' collection."""
    user_id: str
    project_name: str
    chunk_index: int
    content: str
    embedding: list[float]
    metadata: dict
    created_at: datetime

class ProjectDocument(TypedDict):
    """Schema for documents in the 'projects' collection."""
    user_id: str
    name: str
    project_name: str
    documents: list[DocumentInfo]
    chunk_count: int
    created_at: datetime

# ---------------------------------------------------------------------------
# Module-level globals — initialised by init_mongodb() during app lifespan.
# All remain None until then.
# ---------------------------------------------------------------------------
client: AsyncIOMotorClient | None = None
db = None
vectors = None
projects = None
sync_client: MongoClient | None = None
sync_db = None
llm: ChatOpenAI | None = None
embeddings: OpenAIEmbeddings | None = None
vectorstore: MongoDBAtlasVectorSearch | None = None

VECTORS_COLLECTION = "vectors"
PROJECTS_COLLECTION = "projects"
VECTOR_INDEX_NAME = "vector_index"

_llm_cache: dict[str, ChatOllama] = {}
_openrouter_llm_cache: dict[str, ChatOpenAI] = {}
_embeddings_cache: dict[str, OpenAIEmbeddings] = {}
_vectorstore_cache: dict[str, MongoDBAtlasVectorSearch] = {}


def get_embeddings(model: str | None = None) -> OpenAIEmbeddings:
    """Get or create a cached embeddings instance for the specified model."""
    model_name = model or settings.embedding_model
    
    if model_name not in settings.allowed_embedding_models:
        raise ValueError(f"Model '{model_name}' not in allowed embedding models: {settings.allowed_embedding_models}")
    
    if model_name not in _embeddings_cache:
        kwargs = {
            "model": model_name,
            "openai_api_key": settings.openrouter_api_key,
            "openai_api_base": settings.openrouter_base_url,
        }
        if "text-embedding-3" in model_name:
            kwargs["dimensions"] = 1536
        else:
            kwargs["check_embedding_ctx_length"] = False
        
        _embeddings_cache[model_name] = OpenAIEmbeddings(**kwargs)
    
    return _embeddings_cache[model_name]


def get_vectorstore(model: str | None = None) -> MongoDBAtlasVectorSearch:
    """Get or create a cached vectorstore instance for the specified model."""
    model_name = model or settings.embedding_model
    
    if model_name not in _vectorstore_cache:
        embeddings = get_embeddings(model_name)
        _vectorstore_cache[model_name] = MongoDBAtlasVectorSearch(
            collection=sync_db[VECTORS_COLLECTION],
            embedding=embeddings,
            index_name=VECTOR_INDEX_NAME,
            text_key="content",
            embedding_key="embedding",
        )
    
    return _vectorstore_cache[model_name]


def get_llm(model: str) -> ChatOllama:
    """Get or create a cached Ollama LLM instance."""
    if not model:
        raise ValueError("Ollama provider requires a specific model name.")
    cache_key = f"ollama:{model}"

    if cache_key not in _llm_cache:
        _llm_cache[cache_key] = ChatOllama(
            model=model,
            base_url=settings.ollama_base_url,
            temperature=0,
        )

    return _llm_cache[cache_key]


def get_openrouter_llm(model: str) -> ChatOpenAI:
    """Get or create a cached OpenRouter LLM instance."""
    if model not in settings.allowed_models:
        raise ValueError(f"Model '{model}' not in allowed models: {settings.allowed_models}")
    
    cache_key = f"openrouter:{model}"

    if cache_key not in _openrouter_llm_cache:
        _openrouter_llm_cache[cache_key] = ChatOpenAI(
            model=model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0,
        )

    return _openrouter_llm_cache[cache_key]


async def init_mongodb():
    """Initialize MongoDB clients, LLM/embeddings, and vectorstore."""
    global client, db, vectors, projects, sync_client, sync_db, llm, embeddings, vectorstore
    try:
        client = AsyncIOMotorClient(settings.mongodb_uri)
        db = client[settings.mongodb_database]
        vectors = db[VECTORS_COLLECTION]
        projects = db[PROJECTS_COLLECTION]

        sync_client = MongoClient(settings.mongodb_uri)
        sync_db = sync_client[settings.mongodb_database]

        embeddings = get_embeddings()
        vectorstore = get_vectorstore()

        llm = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0,
        )

        await ensure_indexes()
    except Exception as e:
        logger.error("MongoDB init failed: %s", type(e).__name__)
        raise


async def ensure_indexes():
    """Create indexes for vectors and projects collections."""
    await vectors.create_index([("user_id", 1), ("project_name", 1)])
    await vectors.create_index([("metadata.source", 1)])
    await projects.create_index([("user_id", 1), ("project_name", 1)], unique=True)

    existing_indexes = await vectors.list_search_indexes().to_list()
    index_names = [idx["name"] for idx in existing_indexes]

    if VECTOR_INDEX_NAME in index_names:
        logger.info("Dropping existing vector search index to add metadata.source filter")
        await vectors.drop_search_index(VECTOR_INDEX_NAME)

    if VECTOR_INDEX_NAME not in index_names:
        search_index_model = SearchIndexModel(
            definition={
                "fields": [
                    {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"},
                    {"type": "filter", "path": "user_id"},
                    {"type": "filter", "path": "project_name"},
                    {"type": "filter", "path": "metadata.source"},
                ]
            },
            name=VECTOR_INDEX_NAME,
            type="vectorSearch",
        )
        await vectors.create_search_index(model=search_index_model)


async def close_mongodb():
    """Close MongoDB client connections."""
    global client, db, vectors, projects, sync_client, sync_db, llm, embeddings, vectorstore
    if client:
        client.close()
        client = None
        db = None
        vectors = None
        projects = None
    if sync_client:
        sync_client.close()
        sync_client = None
        sync_db = None
    llm = None
    embeddings = None
    vectorstore = None


async def check_collection_exists(user_id: str, project_name: str) -> bool:
    """Check if a project already exists for this user."""
    doc = await projects.find_one({"user_id": user_id, "project_name": project_name})
    return doc is not None


async def create_project(
    user_id: str,
    name: str,
    project_name: str,
    documents: list[dict],
    chunk_count: int,
) -> None:
    """Register a project in the projects collection."""
    await projects.insert_one({
        "user_id": user_id,
        "name": name,
        "project_name": project_name,
        "documents": documents,
        "chunk_count": chunk_count,
        "created_at": datetime.now(UTC),
    })


async def list_collections(user_id: str) -> list[dict]:
    """List all projects for a user with metadata."""
    cursor = projects.find({"user_id": user_id}).sort("created_at", -1)
    results = []
    async for doc in cursor:
        results.append({
            "project_name": doc["project_name"],
            "name": doc.get("name"),
            "documents": doc.get("documents", []),
            "chunk_count": doc["chunk_count"],
            "created_at": doc["created_at"],
        })
    return results


async def delete_collection_cascade(user_id: str, project_name: str) -> dict:
    """Delete all vectors for a project but keep the project metadata."""
    project = await projects.find_one({"user_id": user_id, "project_name": project_name})
    
    if not project:
        return {"deleted_vectors": 0, "found": False}
    
    vec_result = await vectors.delete_many({"user_id": user_id, "project_name": project_name})
    
    await projects.update_one(
        {"user_id": user_id, "project_name": project_name},
        {"$set": {"documents": [], "chunk_count": 0}}
    )
    
    logger.info("Clear vectors: user=%s project=%s vectors=%d", user_id, project_name, vec_result.deleted_count)
    
    return {"deleted_vectors": vec_result.deleted_count, "found": True}


async def delete_project_full(user_id: str, project_name: str) -> dict:
    """Delete all vectors AND the project metadata for a project."""
    project = await projects.find_one({"user_id": user_id, "project_name": project_name})
    
    if not project:
        return {"deleted_vectors": 0, "found": False}
    
    vec_result = await vectors.delete_many({"user_id": user_id, "project_name": project_name})
    
    await projects.delete_one({"user_id": user_id, "project_name": project_name})
    
    logger.info("Full delete: user=%s project=%s vectors=%d", user_id, project_name, vec_result.deleted_count)
    
    return {"deleted_vectors": vec_result.deleted_count, "found": True}


async def get_collection_chunks(user_id: str, project_name: str) -> dict:
    """Fetch all chunks for a project."""
    cursor = vectors.find({"user_id": user_id, "project_name": project_name}).sort("chunk_index", 1)

    chunks = []
    async for doc in cursor:
        chunks.append({
            "id": str(doc["_id"]),
            "text": doc.get("content", ""),
            "metadata": doc.get("metadata", {}),
        })

    return {
        "project_name": project_name,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


async def delete_vectors_by_source(user_id: str, project_name: str, file_name: str) -> int:
    """Delete all vectors for a specific file and update project metadata."""
    result = await vectors.delete_many({
        "user_id": user_id,
        "project_name": project_name,
        "metadata.source": file_name,
    })
    
    if result.deleted_count > 0:
        await projects.update_one(
            {"user_id": user_id, "project_name": project_name},
            {"$pull": {"documents": {"name": file_name}}, "$inc": {"chunk_count": -result.deleted_count}}
        )
    
    logger.info("Delete file vectors: user=%s project=%s file=%s deleted=%d", user_id, project_name, file_name, result.deleted_count)
    return result.deleted_count


async def update_project_metadata(user_id: str, project_name: str, name: str | None = None) -> bool:
    """Update project metadata (name, description, etc.)."""
    update_data = {}
    if name is not None:
        update_data["name"] = name

    if not update_data:
        return False

    result = await projects.update_one(
        {"user_id": user_id, "project_name": project_name},
        {"$set": update_data},
    )
    return result.modified_count > 0


# ---------------------------------------------------------------------------
# Summaries CRUD
# ---------------------------------------------------------------------------




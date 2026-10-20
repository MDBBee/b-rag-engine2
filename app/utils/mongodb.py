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

class VectorDocument(TypedDict):
    """Schema for documents in the 'vectors' collection."""
    user_id: str
    collection_name: str
    chunk_index: int
    content: str
    embedding: list[float]
    metadata: dict
    created_at: datetime

class ProjectDocument(TypedDict):
    """Schema for documents in the 'projects' collection."""
    user_id: str
    name: str
    collection_name: str
    file_name: list[str]
    document_type: list[DocumentInfo]
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
summaries = None
sync_client: MongoClient | None = None
sync_db = None
llm: ChatOpenAI | None = None
embeddings: OpenAIEmbeddings | None = None
vectorstore: MongoDBAtlasVectorSearch | None = None

VECTORS_COLLECTION = "vectors"
PROJECTS_COLLECTION = "projects"
SUMMARIES_COLLECTION = "summaries"
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
        _embeddings_cache[model_name] = OpenAIEmbeddings(
            model=model_name,
            dimensions=1536,  # All models use 1536 dimensions for compatibility
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
        )
    
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
    global client, db, vectors, projects, summaries, sync_client, sync_db, llm, embeddings, vectorstore
    try:
        client = AsyncIOMotorClient(settings.mongodb_uri)
        db = client[settings.mongodb_database]
        vectors = db[VECTORS_COLLECTION]
        projects = db[PROJECTS_COLLECTION]
        summaries = db[SUMMARIES_COLLECTION]

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
    # Compound index on vectors: speeds up chunk listing and deletion
    await vectors.create_index([("user_id", 1), ("collection_name", 1)])
    
    # Index on metadata.source: speeds up file-scoped queries
    await vectors.create_index([("metadata.source", 1)])

    # Unique index on projects: prevents duplicate project entries
    await projects.create_index(
        [("user_id", 1), ("collection_name", 1)],
        unique=True,
    )

    # Index on summaries: speeds up listing by project
    await summaries.create_index([("user_id", 1), ("collection_name", 1), ("created_at", -1)])

    # Vector search index on vectors collection
    existing_indexes = await vectors.list_search_indexes().to_list()
    index_names = [idx["name"] for idx in existing_indexes]

    # Drop existing index to recreate with metadata.source filter
    if VECTOR_INDEX_NAME in index_names:
        logger.info("Dropping existing vector search index to add metadata.source filter")
        await vectors.drop_search_index(VECTOR_INDEX_NAME)

    if VECTOR_INDEX_NAME not in index_names:  # Recreate if missing
        search_index_model = SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "vector",
                        "path": "embedding",
                        "numDimensions": 1536,
                        "similarity": "cosine",
                    },
                    {"type": "filter", "path": "user_id"},
                    {"type": "filter", "path": "collection_name"},
                    {"type": "filter", "path": "metadata.source"},
                ]
            },
            name=VECTOR_INDEX_NAME,
            type="vectorSearch",
        )
        await vectors.create_search_index(model=search_index_model)


async def close_mongodb():
    """Close MongoDB client connections."""
    global client, db, vectors, projects, summaries, sync_client, sync_db, llm, embeddings, vectorstore
    if client:
        client.close()
        client = None
        db = None
        vectors = None
        projects = None
        summaries = None
    if sync_client:
        sync_client.close()
        sync_client = None
        sync_db = None
    llm = None
    embeddings = None
    vectorstore = None


async def check_collection_exists(user_id: str, collection_name: str) -> bool:
    """Check if a project already exists for this user."""
    doc = await projects.find_one(
        {"user_id": user_id, "collection_name": collection_name}
    )
    return doc is not None


async def create_project(
    user_id: str,
    name: str,
    collection_name: str,
    file_name: list[str],
    chunk_count: int,
    document_type: list[DocumentInfo],
) -> None:
    """Register a project in the projects collection."""
    await projects.insert_one({
        "user_id": user_id,
        "name": name,
        "collection_name": collection_name,
        "file_name": file_name,
        "chunk_count": chunk_count,
        "document_type": document_type,
        "created_at": datetime.now(UTC),
    })


async def list_collections(user_id: str) -> list[dict]:
    """List all projects for a user with metadata."""
    cursor = projects.find({"user_id": user_id}).sort("created_at", -1)
    results = []
    async for doc in cursor:
        results.append({
            "collection_name": doc["collection_name"],
            "name": doc.get("name"),
            "file_name": doc.get("file_name", []),
            "document_type": doc.get("document_type", []),
            "chunk_count": doc["chunk_count"],
            "created_at": doc["created_at"],
        })
    return results


async def delete_collection_cascade(user_id: str, collection_name: str) -> dict:
    """Delete a project and all its vectors."""
    proj_result = await projects.delete_one(
        {"user_id": user_id, "collection_name": collection_name}
    )

    if proj_result.deleted_count == 0:
        return {"deleted_vectors": 0}

    vec_result = await vectors.delete_many(
        {"user_id": user_id, "collection_name": collection_name}
    )

    logger.info(
        "Delete project: user=%s collection=%s vectors=%d",
        user_id, collection_name, vec_result.deleted_count,
    )

    return {"deleted_vectors": vec_result.deleted_count}


async def get_collection_chunks(user_id: str, collection_name: str) -> dict:
    """Fetch all chunks for a project."""
    cursor = vectors.find(
        {"user_id": user_id, "collection_name": collection_name}
    ).sort("chunk_index", 1)

    chunks = []
    async for doc in cursor:
        chunks.append({
            "id": str(doc["_id"]),
            "text": doc.get("content", ""),
            "metadata": doc.get("metadata", {}),
        })

    return {
        "collection_name": collection_name,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


async def delete_vectors_by_source(user_id: str, collection_name: str, file_name: str) -> int:
    """Delete all vectors for a specific file (identified by metadata.source)."""
    result = await vectors.delete_many({
        "user_id": user_id,
        "collection_name": collection_name,
        "metadata.source": file_name,
    })
    logger.info(
        "Delete file vectors: user=%s collection=%s file=%s deleted=%d",
        user_id, collection_name, file_name, result.deleted_count,
    )
    return result.deleted_count


async def update_project_metadata(user_id: str, collection_name: str, name: str | None = None) -> bool:
    """Update project metadata (name, description, etc.)."""
    update_data = {}
    if name is not None:
        update_data["name"] = name

    if not update_data:
        return False

    result = await projects.update_one(
        {"user_id": user_id, "collection_name": collection_name},
        {"$set": update_data},
    )
    return result.modified_count > 0


# ---------------------------------------------------------------------------
# Summaries CRUD
# ---------------------------------------------------------------------------


async def save_summary(
    user_id: str,
    collection_name: str,
    markdown_text: str,
    title: str,
) -> str:
    """Save a summary to MongoDB. Returns the summary ID."""
    doc = {
        "user_id": user_id,
        "collection_name": collection_name,
        "summary_markdown": markdown_text,
        "title": title,
        "created_at": datetime.now(UTC),
    }
    result = await summaries.insert_one(doc)
    return str(result.inserted_id)


async def get_summaries(user_id: str, collection_name: str) -> list[dict]:
    """Get all summaries for a project, sorted newest first."""
    cursor = summaries.find(
        {"user_id": user_id, "collection_name": collection_name}
    ).sort("created_at", -1)

    results = []
    async for doc in cursor:
        results.append({
            "id": str(doc["_id"]),
            "collection_name": doc["collection_name"],
            "title": doc["title"],
            "summary_markdown": doc["summary_markdown"],
            "created_at": doc["created_at"],
        })
    return results


async def get_summary(user_id: str, summary_id: str) -> dict | None:
    """Get a single summary by ID."""
    from bson import ObjectId

    doc = await summaries.find_one({
        "user_id": user_id,
        "_id": ObjectId(summary_id),
    })
    if not doc:
        return None

    return {
        "id": str(doc["_id"]),
        "collection_name": doc["collection_name"],
        "title": doc["title"],
        "summary_markdown": doc["summary_markdown"],
        "created_at": doc["created_at"],
    }


async def delete_summary(user_id: str, summary_id: str) -> bool:
    """Delete a summary. Returns True if deleted."""
    from bson import ObjectId

    result = await summaries.delete_one({
        "user_id": user_id,
        "_id": ObjectId(summary_id),
    })
    return result.deleted_count > 0

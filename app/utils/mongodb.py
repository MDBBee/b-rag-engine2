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
    file_name: str
    chunk_count: int
    document_type: str
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

        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
        )

        llm = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0,
        )

        vectorstore = MongoDBAtlasVectorSearch(
            collection=sync_db[VECTORS_COLLECTION],
            embedding=embeddings,
            index_name=VECTOR_INDEX_NAME,
            text_key="content",
            embedding_key="embedding",
        )

        await ensure_indexes()
    except Exception as e:
        logger.error("MongoDB init failed: %s", type(e).__name__)
        raise


async def ensure_indexes():
    """Create indexes for vectors and projects collections."""
    # Compound index on vectors: speeds up chunk listing and deletion
    await vectors.create_index([("user_id", 1), ("collection_name", 1)])

    # Unique index on projects: prevents duplicate project entries
    await projects.create_index(
        [("user_id", 1), ("collection_name", 1)],
        unique=True,
    )

    # Vector search index on vectors collection
    existing_indexes = await vectors.list_search_indexes().to_list()
    index_names = [idx["name"] for idx in existing_indexes]

    if VECTOR_INDEX_NAME not in index_names:
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
    file_name: str,
    chunk_count: int,
    document_type: str,
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
            "file_name": doc.get("file_name"),
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

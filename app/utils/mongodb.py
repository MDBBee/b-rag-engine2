import logging

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.operations import SearchIndexModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch

from app.config import settings

logger = logging.getLogger(__name__)

# Async MongoDB client (for direct operations)
client: AsyncIOMotorClient | None = None
db = None
vectors = None

# Sync MongoDB client (for langchain-mongodb vectorstore)
sync_client: MongoClient | None = None
sync_db = None

# Shared LLM/embedding instances
llm: ChatOpenAI | None = None
embeddings: OpenAIEmbeddings | None = None
vectorstore: MongoDBAtlasVectorSearch | None = None

VECTORS_COLLECTION = "vectors"
VECTOR_INDEX_NAME = "vector_index"


async def init_mongodb():
    """Initialize MongoDB clients, LLM/embeddings, and vectorstore."""
    global client, db, vectors, sync_client, sync_db, llm, embeddings, vectorstore
    try:
        client = AsyncIOMotorClient(settings.mongodb_uri)
        db = client[settings.mongodb_database]
        vectors = db[VECTORS_COLLECTION]

        sync_client = MongoClient(settings.mongodb_uri)
        sync_db = sync_client[settings.mongodb_database]

        llm = ChatOpenAI(
            model=settings.llm_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=0,
        )
        embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
        )

        vectorstore = MongoDBAtlasVectorSearch(
            collection=sync_db[VECTORS_COLLECTION],
            embedding=embeddings,
            index_name=VECTOR_INDEX_NAME,
            text_key="content",
            embedding_key="embedding",
        )

        await ensure_indexes()
        logger.info("MongoDB initialized")
    except Exception as e:
        logger.error(f"MongoDB init failed: {e}")
        raise


async def ensure_indexes():
    """Create collections and vector search index if they don't exist."""
    await vectors.create_index(
        [("user_id", 1), ("collection_name", 1)],
    )

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
        logger.info("Created vector search index: %s", VECTOR_INDEX_NAME)
    else:
        logger.info("Vector search index already exists: %s", VECTOR_INDEX_NAME)


async def close_mongodb():
    """Close MongoDB client connections."""
    global client, db, vectors, sync_client, sync_db, llm, embeddings, vectorstore
    if client:
        client.close()
        client = None
        db = None
        vectors = None
    if sync_client:
        sync_client.close()
        sync_client = None
        sync_db = None
    llm = None
    embeddings = None
    vectorstore = None
    logger.info("MongoDB connection closed")


async def check_collection_exists(user_id: str, collection_name: str) -> bool:
    """Check if a collection already exists for this user."""
    count = await vectors.count_documents(
        {"user_id": user_id, "collection_name": collection_name}
    )
    return count > 0


async def list_collections(user_id: str) -> list[dict]:
    """List all collections for a user with chunk counts."""
    cursor = vectors.aggregate([
        {"$match": {"user_id": user_id}},
        {"$group": {
            "_id": "$collection_name",
            "chunk_count": {"$sum": 1},
            "created_at": {"$min": "$created_at"},
        }},
        {"$sort": {"created_at": -1}},
    ])
    results = []
    async for doc in cursor:
        results.append({
            "collection_name": doc["_id"],
            "chunk_count": doc["chunk_count"],
            "created_at": doc["created_at"],
        })
    return results


async def delete_collection_cascade(user_id: str, collection_name: str) -> dict:
    """Delete all vectors for a collection."""
    vec_result = await vectors.delete_many(
        {"user_id": user_id, "collection_name": collection_name}
    )

    logger.info(
        "Delete collection: user=%s collection=%s vectors=%d",
        user_id, collection_name, vec_result.deleted_count,
    )

    return {
        "deleted_vectors": vec_result.deleted_count,
    }


async def get_collection_chunks(user_id: str, collection_name: str) -> dict:
    """Fetch all chunks for a collection."""
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

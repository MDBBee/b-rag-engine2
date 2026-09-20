import logging
from datetime import datetime, timezone

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
conversations = None

# Sync MongoDB client (for LangChain/LangGraph integrations)
sync_client: MongoClient | None = None
sync_db = None

# Shared LLM/embedding instances
llm: ChatOpenAI | None = None
embeddings: OpenAIEmbeddings | None = None
vectorstore: MongoDBAtlasVectorSearch | None = None

VECTORS_COLLECTION = "vectors"
CONVERSATIONS_COLLECTION = "conversations"
VECTOR_INDEX_NAME = "vector_index"


async def init_mongodb():
    """Initialize MongoDB clients, LLM/embeddings, and vectorstore."""
    global client, db, vectors, conversations, sync_client, sync_db, llm, embeddings, vectorstore
    try:
        # Async client for direct operations
        client = AsyncIOMotorClient(settings.mongodb_uri)
        db = client[settings.mongodb_database]
        vectors = db[VECTORS_COLLECTION]
        conversations = db[CONVERSATIONS_COLLECTION]

        # Sync client for LangChain/LangGraph
        sync_client = MongoClient(settings.mongodb_uri)
        sync_db = sync_client[settings.mongodb_database]

        # Shared LLM and embeddings
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

        # Vectorstore (shared instance, pre_filter passed at query time)
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
    await conversations.create_index(
        [("user_id", 1), ("collection_name", 1), ("thread_id", 1)],
        unique=True,
    )
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
    global client, db, vectors, conversations, sync_client, sync_db, llm, embeddings, vectorstore
    if client:
        client.close()
        client = None
        db = None
        vectors = None
        conversations = None
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
    """Cascade delete vectors, conversations, and checkpoints for a collection."""
    conv_docs = await conversations.find(
        {"user_id": user_id, "collection_name": collection_name}
    ).to_list()
    thread_ids = [doc["thread_id"] for doc in conv_docs]

    deleted_checkpoints = 0
    for thread_id in thread_ids:
        result = await db.checkpoints.delete_many({"thread_id": thread_id})
        deleted_checkpoints += result.deleted_count
        result = await db.checkpoint_writes.delete_many({"thread_id": thread_id})
        deleted_checkpoints += result.deleted_count

    conv_result = await conversations.delete_many(
        {"user_id": user_id, "collection_name": collection_name}
    )

    vec_result = await vectors.delete_many(
        {"user_id": user_id, "collection_name": collection_name}
    )

    logger.info(
        "Cascade delete: user=%s collection=%s vectors=%d conversations=%d checkpoints=%d",
        user_id, collection_name,
        vec_result.deleted_count, conv_result.deleted_count, deleted_checkpoints,
    )

    return {
        "deleted_vectors": vec_result.deleted_count,
        "deleted_conversations": conv_result.deleted_count,
        "deleted_checkpoints": deleted_checkpoints,
    }


async def ensure_conversation_metadata(user_id: str, collection_name: str, thread_id: str):
    """Create conversation metadata entry if it doesn't exist."""
    now = datetime.now(timezone.utc)
    await conversations.update_one(
        {"user_id": user_id, "collection_name": collection_name, "thread_id": thread_id},
        {"$setOnInsert": {
            "user_id": user_id,
            "collection_name": collection_name,
            "thread_id": thread_id,
            "created_at": now,
            "updated_at": now,
        }},
        upsert=True,
    )

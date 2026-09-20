# MongoDB Migration Summary

## Overview
Successfully migrated from ChromaDB + SQLite to MongoDB Atlas for vector storage and conversation management.

## Architecture Changes

### Before
- **Vector Storage**: ChromaDB (local files)
- **Conversation Storage**: SQLite (local file)
- **User Isolation**: None (single-tenant)

### After
- **Vector Storage**: MongoDB Atlas with vector search
- **Conversation Storage**: MongoDB Atlas + LangGraph checkpointer
- **User Isolation**: Full multi-tenant support via `user_id`

## Database Schema

### Collections
1. **vectors** - Document chunks with embeddings
   - Fields: `user_id`, `collection_name`, `chunk_index`, `content`, `embedding`, `metadata`, `created_at`
   - Indexes: Compound index on `(user_id, collection_name)`, vector search index on `embedding`

2. **conversations** - Conversation metadata
   - Fields: `user_id`, `collection_name`, `thread_id`, `created_at`, `updated_at`
   - Indexes: Unique compound index on `(user_id, collection_name, thread_id)`

3. **checkpoints** - LangGraph conversation state (managed by LangGraph)
4. **checkpoint_writes** - LangGraph intermediate writes (managed by LangGraph)

## API Changes

### New Endpoints
- `GET /collections?user_id={user_id}` - List user's collections
- `DELETE /collections/{collection_name}?user_id={user_id}` - Cascade delete collection

### Updated Endpoints
- `POST /ingest` - Now requires `user_id` parameter
- `POST /query/stream` - Now requires `user_id` parameter

### Response Changes
- Ingestion returns 409 Conflict if collection already exists for user
- Cascade delete returns counts of deleted vectors, conversations, and checkpoints

## Code Simplifications

### Removed Over-Engineering
1. **Removed `asyncio.to_thread()`** - FastAPI handles concurrency at request level
2. **Removed getter functions** - Direct access to module-level variables (`mongodb.vectors`, `mongodb.conversations`)
3. **Simplified initialization** - Single `init_mongodb()` function, no complex dependency injection

### Module-Level Variables
```python
# mongodb.py
client: AsyncIOMotorClient | None = None
db = None
vectors = None
conversations = None
```

Access pattern:
```python
from app.utils import mongodb
await mongodb.vectors.insert_many(docs)
```

## Key Features

### User Isolation
- All operations filtered by `user_id`
- Collection names unique per user
- Cascade delete removes all user data for a collection

### Vector Search
- MongoDB Atlas Vector Search with 1536 dimensions (OpenAI embeddings)
- Pre-filtering by `user_id` and `collection_name`
- Cosine similarity metric

### Conversation Memory
- LangGraph's `MongoDBSaver` for checkpoint management
- Automatic thread_id generation
- Full conversation history in state

### Cascade Delete
When deleting a collection:
1. Find all conversation thread_ids for the collection
2. Delete checkpoints and checkpoint_writes for those threads
3. Delete conversation metadata
4. Delete all vectors

## Testing Results

✅ Ingestion: 184 chunks stored successfully
✅ Collection uniqueness: 409 Conflict on duplicate
✅ Collection listing: Returns collections with chunk counts
✅ Vector search: 5 documents found with pre-filtering
✅ Query streaming: Sources + answer returned
✅ Cascade delete: 184 vectors, 3 conversations, 37 checkpoints deleted

## Dependencies

### Added
- `motor` - Async MongoDB driver
- `langchain-mongodb` - MongoDB vector store integration
- `langgraph-checkpoint-mongodb` - MongoDB checkpointer for LangGraph

### Removed
- `langchain-chroma` - ChromaDB integration
- `langgraph-checkpoint-sqlite` - SQLite checkpointer
- `chromadb` - ChromaDB client
- `aiosqlite` - Async SQLite driver

## Configuration

### Environment Variables
```bash
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/
MONGODB_DATABASE=b-rag
```

### Settings
- `mongodb_uri` - MongoDB connection string
- `mongodb_database` - Database name (default: "b-rag")

## Migration Steps Completed

1. ✅ Phase 1: MongoDB Atlas setup
2. ✅ Phase 2: Dependencies installed
3. ✅ Phase 3: config.py updated
4. ✅ Phase 4: mongodb.py created
5. ✅ Phase 5: factories.py updated
6. ✅ Phase 6: ingestion_pipeline.py updated
7. ✅ Phase 7: retrieval_pipeline.py updated
8. ✅ Phase 8: schemas.py updated
9. ✅ Phase 9: Routers updated
10. ✅ Phase 10: main.py updated
11. ✅ Phase 11: .env.example updated
12. ✅ Phase 12: Testing complete

## Next Steps

- Phase 5: Production hardening (auth, rate limiting, deployment)

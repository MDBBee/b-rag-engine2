import logging
from fastapi import APIRouter, HTTPException, Query

from app.utils.mongodb import list_collections, delete_collection_cascade
from app.typing.schemas import CollectionInfo, CascadeDeleteResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/collections", response_model=list[CollectionInfo])
async def get_collections(user_id: str = Query(...)):
    """List all collections for a user."""
    try:
        collections = await list_collections(user_id)
        return collections
    except Exception as e:
        logger.error(f"Failed to list collections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list collections")


@router.delete("/collections/{collection_name}", response_model=CascadeDeleteResponse)
async def delete_collection(collection_name: str, user_id: str = Query(...)):
    """Delete a collection and all associated data (vectors, conversations, checkpoints)."""
    try:
        result = await delete_collection_cascade(user_id, collection_name)
        if result["deleted_vectors"] == 0 and result["deleted_conversations"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete collection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete collection")
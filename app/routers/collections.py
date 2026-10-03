import logging

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import (
    CascadeDeleteResponse,
    CollectionChunksResponse,
    CollectionInfo,
)
from app.utils.mongodb import (
    delete_collection_cascade,
    get_collection_chunks,
    list_collections,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[CollectionInfo])
async def get_collections(user: UserInfo = Depends(get_current_user)):
    """List all collections for a user."""
    try:
        collections = await list_collections(user.id)
        return collections
    except Exception:
        logger.exception("Failed to list collections")
        raise HTTPException(status_code=500, detail="Failed to list collections")


@router.get("/{collection_name}/chunks", response_model=CollectionChunksResponse)
async def get_chunks(collection_name: str, user: UserInfo = Depends(get_current_user)):
    """Fetch all chunks for a collection (for visualization page)."""
    try:
        result = await get_collection_chunks(user.id, collection_name)
        if result["chunk_count"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch chunks")
        raise HTTPException(status_code=500, detail="Failed to fetch chunks")


@router.delete("/{collection_name}", response_model=CascadeDeleteResponse)
async def delete_collection(collection_name: str, user: UserInfo = Depends(get_current_user)):
    """Delete a collection and all associated vectors."""
    try:
        result = await delete_collection_cascade(user.id, collection_name)
        if result["deleted_vectors"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete collection")
        raise HTTPException(status_code=500, detail="Failed to delete collection")

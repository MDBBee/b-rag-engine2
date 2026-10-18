import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import (
    CascadeDeleteResponse,
    CollectionChunksResponse,
    CollectionInfo,
    CollectionUpdateRequest,
)
from app.utils.mongodb import (
    delete_collection_cascade,
    delete_vectors_by_source,
    get_collection_chunks,
    list_collections,
    projects,
    update_project_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
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


@router.get("/{collection_name}/metadata")
async def get_collection_metadata(collection_name: str, user: UserInfo = Depends(get_current_user)):
    """Get metadata for a specific collection."""
    try:
        result = await get_collection_chunks(user.id, collection_name)
        if result["chunk_count"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        
        # Get project metadata from projects collection
        project_doc = await projects.find_one({
            "user_id": user.id,
            "collection_name": collection_name,
        })
        
        if not project_doc:
            raise HTTPException(status_code=404, detail=f"Project metadata for '{collection_name}' not found")
        
        return {
            "collection_name": collection_name,
            "name": project_doc.get("name"),
            "file_name": project_doc.get("file_name", []),
            "document_type": project_doc.get("document_type", []),
            "chunk_count": project_doc.get("chunk_count", result["chunk_count"]),
            "created_at": project_doc.get("created_at"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get collection metadata")
        raise HTTPException(status_code=500, detail="Failed to get collection metadata")


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


@router.get("/{collection_name}/documents")
async def get_documents(collection_name: str, user: UserInfo = Depends(get_current_user)):
    """Get all documents in a collection with metadata."""
    try:
        project_doc = await projects.find_one({
            "user_id": user.id,
            "collection_name": collection_name,
        })

        if not project_doc:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")

        return {
            "collection_name": collection_name,
            "documents": project_doc.get("document_type", []),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get documents")
        raise HTTPException(status_code=500, detail="Failed to get documents")


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


@router.delete("/{collection_name}/documents", response_model=CascadeDeleteResponse)
async def delete_document(
    collection_name: str,
    file_name: str = Query(...),
    user: UserInfo = Depends(get_current_user),
):
    """Delete all vectors for a specific file within a collection."""
    try:
        deleted = await delete_vectors_by_source(user.id, collection_name, file_name)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"No vectors found for file '{file_name}'")
        return CascadeDeleteResponse(deleted_vectors=deleted)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete document vectors")
        raise HTTPException(status_code=500, detail="Failed to delete document vectors")


@router.patch("/{collection_name}")
async def update_collection(
    collection_name: str,
    request: CollectionUpdateRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Update project metadata (name, description, etc.)."""
    try:
        updated = await update_project_metadata(
            user.id, collection_name, name=request.name
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Collection '{collection_name}' not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update collection metadata")
        raise HTTPException(status_code=500, detail="Failed to update collection metadata")

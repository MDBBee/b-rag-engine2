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


@router.get("/{project_name}/metadata")
async def get_collection_metadata(project_name: str, user: UserInfo = Depends(get_current_user)):
    """Get metadata for a specific collection."""
    try:
        result = await get_collection_chunks(user.id, project_name)
        if result["chunk_count"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")
        
        # Get project metadata from projects collection
        project_doc = await projects.find_one({
            "user_id": user.id,
            "project_name": project_name,
        })
        
        if not project_doc:
            raise HTTPException(status_code=404, detail=f"Project metadata for '{project_name}' not found")
        
        return {
            "project_name": project_name,
            "name": project_doc.get("name"),
            "documents": project_doc.get("documents", []),
            "chunk_count": project_doc.get("chunk_count", result["chunk_count"]),
            "created_at": project_doc.get("created_at"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get collection metadata")
        raise HTTPException(status_code=500, detail="Failed to get collection metadata")


@router.get("/{project_name}/chunks", response_model=CollectionChunksResponse)
async def get_chunks(project_name: str, user: UserInfo = Depends(get_current_user)):
    """Fetch all chunks for a collection (for visualization page)."""
    try:
        result = await get_collection_chunks(user.id, project_name)
        if result["chunk_count"] == 0:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to fetch chunks")
        raise HTTPException(status_code=500, detail="Failed to fetch chunks")


@router.get("/{project_name}/documents")
async def get_documents(project_name: str, user: UserInfo = Depends(get_current_user)):
    """Get all documents in a collection with metadata."""
    try:
        project_doc = await projects.find_one({
            "user_id": user.id,
            "project_name": project_name,
        })

        if not project_doc:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")

        return {
            "project_name": project_name,
            "documents": project_doc.get("documents", []),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get documents")
        raise HTTPException(status_code=500, detail="Failed to get documents")


@router.delete("/{project_name}", response_model=CascadeDeleteResponse)
async def delete_collection(project_name: str, user: UserInfo = Depends(get_current_user)):
    """Delete all vectors for a collection but keep the project."""
    try:
        result = await delete_collection_cascade(user.id, project_name)
        if not result["found"]:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to clear collection vectors")
        raise HTTPException(status_code=500, detail="Failed to clear collection vectors")


@router.delete("/{project_name}/documents", response_model=CascadeDeleteResponse)
async def delete_document(
    project_name: str,
    file_name: str = Query(...),
    user: UserInfo = Depends(get_current_user),
):
    """Delete all vectors for a specific file within a collection."""
    try:
        deleted = await delete_vectors_by_source(user.id, project_name, file_name)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"No vectors found for file '{file_name}'")
        return CascadeDeleteResponse(deleted_vectors=deleted)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete document vectors")
        raise HTTPException(status_code=500, detail="Failed to delete document vectors")


@router.patch("/{project_name}")
async def update_collection(
    project_name: str,
    request: CollectionUpdateRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Update project metadata (name, description, etc.)."""
    try:
        updated = await update_project_metadata(
            user.id, project_name, name=request.name
        )
        if not updated:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to update collection metadata")
        raise HTTPException(status_code=500, detail="Failed to update collection metadata")

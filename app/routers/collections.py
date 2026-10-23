import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query

from app.config import settings
from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import (
    CascadeDeleteResponse,
    CollectionChunksResponse,
    CollectionInfo,
    CollectionUpdateRequest,
)
from app.utils import mongodb
from app.utils.mongodb import (
    delete_collection_cascade,
    delete_project_full,
    delete_vectors_by_source,
    get_collection_chunks,
    list_collections,
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
        project_doc = await mongodb.projects.find_one({
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
async def get_chunks(
    project_name: str,
    file_name: Annotated[list[str] | None, Query()] = None,
    user: UserInfo = Depends(get_current_user),
):
    """Fetch all chunks for a collection (for visualization page).
    
    Use file_name to filter by specific documents (repeat param: ?file_name=a&file_name=b).
    """
    try:
        result = await get_collection_chunks(user.id, project_name, file_scope=file_name)
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
        project_doc = await mongodb.projects.find_one({
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


@router.post("/{project_name}/documents/{file_name}/recalculate-tokens")
async def recalculate_document_tokens(
    project_name: str,
    file_name: str,
    user: UserInfo = Depends(get_current_user),
):
    """Recalculate token count for a specific document."""
    try:
        from app.utils.token_counter import count_tokens

        # Get project to find embedding model
        project_doc = await mongodb.projects.find_one({
            "user_id": user.id,
            "project_name": project_name,
        })

        if not project_doc:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")

        # Find document in project
        documents = project_doc.get("documents", [])
        doc_info = next((d for d in documents if d["name"] == file_name), None)
        
        if not doc_info:
            raise HTTPException(status_code=404, detail=f"Document '{file_name}' not found")

        # Get all chunks for this file
        cursor = mongodb.vectors.find({
            "user_id": user.id,
            "project_name": project_name,
            "metadata.source": file_name,
        })

        # Count tokens using the embedding model
        embedding_model = doc_info.get("embedding_model") or settings.embedding_model
        total_tokens = 0
        async for chunk in cursor:
            total_tokens += count_tokens(chunk.get("content", ""), embedding_model)

        # Update document in MongoDB
        await mongodb.projects.update_one(
            {"user_id": user.id, "project_name": project_name},
            {
                "$set": {
                    "documents.$[elem].token_count": total_tokens,
                }
            },
            array_filters=[{"elem.name": file_name}]
        )

        return {"status": "ok", "token_count": total_tokens}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to recalculate tokens")
        raise HTTPException(status_code=500, detail="Failed to recalculate tokens")


@router.delete("/{project_name}", response_model=CascadeDeleteResponse)
async def delete_collection(
    project_name: str,
    persist_vectors: bool = Form(True),
    user: UserInfo = Depends(get_current_user),
):
    """Delete vectors for a collection. If persist_vectors=false, delete the project entirely."""
    try:
        if persist_vectors:
            result = await delete_collection_cascade(user.id, project_name)
        else:
            result = await delete_project_full(user.id, project_name)
        if not result["found"]:
            raise HTTPException(status_code=404, detail=f"Collection '{project_name}' not found")
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete collection")
        raise HTTPException(status_code=500, detail="Failed to delete collection")


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

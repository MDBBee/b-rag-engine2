import logging

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import SummaryResponse, SummarySaveRequest
from app.utils import mongodb

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/summaries",
    tags=["summaries"],
)


def _auto_title(markdown_text: str) -> str:
    """Generate title from first 50 chars of summary content."""
    clean = markdown_text.strip()
    clean = clean.lstrip("#").strip()
    clean = clean.replace("**", "").replace("*", "")
    if len(clean) <= 50:
        return clean or "Summary"
    truncated = clean[:50].rsplit(" ", 1)[0]
    return f"{truncated}..."


@router.post("/save", response_model=SummaryResponse)
async def save_summary(
    request: SummarySaveRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Save a summary to MongoDB."""
    title = request.title or _auto_title(request.markdown_text)

    summary_id = await mongodb.save_summary(
        user_id=user.id,
        collection_name=request.collection_name,
        markdown_text=request.markdown_text,
        title=title,
    )

    saved = await mongodb.get_summary(user.id, summary_id)
    if not saved:
        raise HTTPException(status_code=500, detail="Failed to save summary")

    return SummaryResponse(**saved)


@router.get("/list/{collection_name}", response_model=list[SummaryResponse])
async def list_summaries(
    collection_name: str,
    user: UserInfo = Depends(get_current_user),
):
    """Get all summaries for a project."""
    summaries = await mongodb.get_summaries(user.id, collection_name)
    return [SummaryResponse(**s) for s in summaries]


@router.get("/{summary_id}", response_model=SummaryResponse)
async def get_summary(
    summary_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Get a single summary by ID."""
    summary = await mongodb.get_summary(user.id, summary_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not found")
    return SummaryResponse(**summary)


@router.delete("/{summary_id}")
async def delete_summary(
    summary_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Delete a summary."""
    success = await mongodb.delete_summary(user.id, summary_id)
    if not success:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"status": "deleted", "id": summary_id}

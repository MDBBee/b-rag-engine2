import json
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.middleware.auth import UserInfo, get_current_user
from app.utils.ingestion_pipeline import ingestion_pipeline_stream
from app.utils.transcript_fetcher import fetch_transcript_with_retry, raise_for_transcript_error
from app.utils.youtube_utils import YouTubeURLRequest, extract_video_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["ingestion"],
)

MAX_COLLECTION_NAME_LENGTH = 40


def video_id_to_collection_name(video_id: str) -> str:
    """Convert video ID to collection name: 'dQw4w9WgXcQ' -> 'yt_dqw4w9wgxcq'"""
    name = f"yt_{video_id}"
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    if not name:
        return f"yt_{uuid.uuid4().hex[:8]}"
    return name[:MAX_COLLECTION_NAME_LENGTH]


@router.post("/youtube")
async def ingest_youtube_stream(
    request: YouTubeURLRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Streaming YouTube ingestion endpoint. Returns SSE events with progress updates."""
    video_id = extract_video_id(request.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

    transcript_result = await fetch_transcript_with_retry(video_id, request.languages)
    raise_for_transcript_error(transcript_result, video_id)

    full_text = transcript_result["full_text"]
    language = transcript_result.get("language", "unknown")
    collection_name = request.collection_name or video_id_to_collection_name(video_id)
    filename = request.file_name or f"youtube_{video_id}.txt"

    async def event_generator():
        try:
            async for event_type, data in ingestion_pipeline_stream(
                file_path=None,
                filename=filename,
                collection_name=collection_name,
                user_id=user.id,
                project_name=f"YouTube: {video_id}",
                transcript_text=full_text,
            ):
                payload = json.dumps({"type": event_type, **data})
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("YouTube ingestion stream failed for %s", video_id)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Ingestion failed'})}\n\n"

    logger.info("YouTube ingestion streaming: video=%s lang=%s", video_id, language)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

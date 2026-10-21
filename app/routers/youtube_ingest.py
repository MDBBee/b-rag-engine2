import json
import logging
import re
import uuid
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.sse import EventSourceResponse

from app.limiter import limiter
from app.middleware.auth import UserInfo, get_current_user
from app.utils.ingestion_pipeline import ingestion_pipeline_stream
from app.utils.transcript_fetcher import fetch_transcript_with_retry, raise_for_transcript_error
from app.utils.youtube_utils import YouTubeURLRequest, extract_video_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["ingestion"],
)

MAX_PROJECT_NAME_LENGTH = 40


def video_id_to_project_name(video_id: str) -> str:
    """Convert video ID to project name: 'dQw4w9WgXcQ' -> 'yt_dqw4w9wgxcq'"""
    name = f"yt_{video_id}"
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")
    if not name:
        return f"yt_{uuid.uuid4().hex[:8]}"
    return name[:MAX_PROJECT_NAME_LENGTH]


@router.post("/youtube")
@limiter.limit("5/minute")
async def ingest_youtube_stream(
    request: Request,
    query: YouTubeURLRequest,
    user: UserInfo = Depends(get_current_user),
) -> EventSourceResponse:
    """Streaming YouTube ingestion endpoint. Returns SSE events with progress updates."""
    video_id = extract_video_id(query.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

    transcript_result = await fetch_transcript_with_retry(video_id, query.languages)
    raise_for_transcript_error(transcript_result, video_id)

    full_text = transcript_result["full_text"]
    language = transcript_result.get("language", "unknown")
    project_name = query.project_name or video_id_to_project_name(video_id)
    filename = query.file_name or f"youtube_{video_id}.txt"

    logger.info("YouTube ingestion streaming: video=%s lang=%s", video_id, language)

    async def _stream() -> AsyncIterable[str]:
        try:
            async for event_type, data in ingestion_pipeline_stream(
                file_path=None,
                filename=filename,
                project_name=project_name,
                user_id=user.id,
                transcript_text=full_text,
            ):
                payload = json.dumps({"type": event_type, **data})
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("YouTube ingestion stream failed for %s", video_id)
            error_payload = json.dumps({"type": "error", "message": "Ingestion failed"})
            yield f"data: {error_payload}\n\n"

    return EventSourceResponse(_stream())

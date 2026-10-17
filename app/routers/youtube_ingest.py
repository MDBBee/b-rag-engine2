import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import IngestResponse
from app.utils.ingestion_pipeline import ingestion_pipeline
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


@router.post("/youtube", response_model=IngestResponse)
async def ingest_youtube(
    request: YouTubeURLRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Ingest a YouTube video transcript into the RAG pipeline.

    Fetches the transcript, chunks it, embeds, and stores in MongoDB.
    """
    video_id = extract_video_id(request.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video ID from URL")

    transcript_result = await fetch_transcript_with_retry(video_id, request.languages)
    raise_for_transcript_error(transcript_result, video_id)

    full_text = transcript_result["full_text"]
    language = transcript_result.get("language", "unknown")
    collection_name = request.collection_name or video_id_to_collection_name(video_id)
    filename = request.file_name or f"youtube_{video_id}.txt"

    try:
        chunk_count, document_type, no_of_pages, first_chunk_index, chunks, summarized_chunks = await ingestion_pipeline(
            file_path=None,
            filename=filename,
            collection_name=collection_name,
            user_id=user.id,
            project_name=f"YouTube: {video_id}",
            transcript_text=full_text,
        )
        logger.info(
            "YouTube ingestion complete: video=%s lang=%s chunks=%d",
            video_id, language, chunk_count,
        )
        return IngestResponse(
            status="ok",
            chunk_count=chunk_count,
            document_type=document_type,
            no_of_pages=no_of_pages,
            first_chunk_index=first_chunk_index,
            last_chunk_index=first_chunk_index + chunk_count - 1 if chunk_count > 0 else first_chunk_index,
            chunks=chunks,
            summarized_chunks=summarized_chunks,
        )
    except ValueError as e:
        logger.warning("Collection uniqueness violation: %s", e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        logger.exception("YouTube ingestion failed for %s", video_id)
        raise HTTPException(status_code=500, detail="Ingestion failed. Please try again.")

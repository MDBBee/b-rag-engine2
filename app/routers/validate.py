import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.middleware.auth import UserInfo, get_current_user
from app.utils.transcript_fetcher import fetch_transcript_with_retry
from app.utils.youtube_utils import extract_video_id, validate_youtube_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/validate",
    tags=["validation"],
)


class VideoValidationRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        is_valid, error, _ = validate_youtube_url(v)
        if not is_valid:
            raise ValueError(error)
        return v


class VideoValidationResponse(BaseModel):
    valid: bool
    video_id: str
    message: str


@router.post("/video", response_model=VideoValidationResponse)
async def validate_video(
    query: VideoValidationRequest,
    user: UserInfo = Depends(get_current_user),
) -> VideoValidationResponse:
    """Validate YouTube URL and check if video is accessible with transcript.

    Returns video_id if valid, raises HTTPException with error details if invalid.
    """
    video_id = extract_video_id(query.url)
    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Could not extract video ID from URL",
        )

    transcript_result = await fetch_transcript_with_retry(video_id)

    if not transcript_result["success"]:
        error_name = transcript_result.get("error_name", "")
        error_msg = transcript_result.get("error", "Unknown error")
        status_code = transcript_result.get("status_code", 500)

        error_messages = {
            "TranscriptsDisabled": "Transcripts are disabled for this video",
            "AgeRestricted": "This video is age-restricted. Transcript access requires a signed-in YouTube session",
            "VideoUnplayable": "This video is unplayable (possibly region-locked)",
            "VideoUnavailable": "This video is unavailable (deleted or private)",
            "InvalidVideoId": "Invalid YouTube video ID",
            "NoTranscriptFound": "No transcript found for this video",
            "RequestBlocked": "YouTube is temporarily blocking requests. Please try again later",
            "IpBlocked": "YouTube is temporarily blocking this server's IP. Please try again later",
            "TooManyRequests": "Too many requests to YouTube. Please try again later",
            "YouTubeDataUnparsable": "YouTube returned unparseable data. Please try again later",
            "YouTubeRequestFailed": "YouTube request failed. Please try again later",
        }

        detail = error_messages.get(error_name, f"Failed to validate video: {error_msg}")
        logger.warning("Video validation failed for %s: %s", video_id, detail)

        raise HTTPException(status_code=status_code, detail=detail)

    logger.info("Video validated successfully: %s", video_id)

    return VideoValidationResponse(
        valid=True,
        video_id=video_id,
        message="Video validated successfully",
    )

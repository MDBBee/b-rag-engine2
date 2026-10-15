import asyncio
import logging

from fastapi import HTTPException
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


async def fetch_transcript(video_id: str, languages: list[str] | None = None) -> dict:
    """Fetch transcript for a YouTube video.

    Args:
        video_id: 11-character YouTube video ID
        languages: Preferred language codes (e.g., ['en', 'es']).
                   If None or empty, fetches any available transcript.

    Returns:
        dict with keys: success, video_id, language, full_text, segment_count
        On failure: success=False, error=str, retryable=bool
    """
    langs = languages or []

    try:
        ytt_api = YouTubeTranscriptApi()

        transcript = await asyncio.to_thread(
            ytt_api.fetch, video_id, languages=langs if langs else None
        )

        formatter = TextFormatter()
        full_text = formatter.format_transcript(transcript)

        language = transcript.language_code if hasattr(transcript, "language_code") else (langs[0] if langs else "unknown")

        return {
            "success": True,
            "video_id": video_id,
            "language": language,
            "full_text": full_text.strip(),
            "segment_count": len(transcript.snippets) if hasattr(transcript, "snippets") else 0,
        }

    except Exception as e:
        error_name = type(e).__name__
        error_msg = str(e)
        logger.warning("Transcript fetch failed for %s: %s — %s", video_id, error_name, error_msg)

        retryable = _is_retryable(error_name)

        status_code = _map_error_to_status(error_name, error_msg)

        return {
            "success": False,
            "error": error_msg,
            "error_name": error_name,
            "retryable": retryable,
            "status_code": status_code,
        }


def _is_retryable(error_name: str) -> bool:
    """Determine if an error is transient and worth retrying."""
    transient_errors = {
        "RequestBlocked",
        "IpBlocked",
        "YouTubeDataUnparsable",
        "YouTubeRequestFailed",
        "TooManyRequests",
        "VideoUnavailable",
    }
    return error_name in transient_errors


def _map_error_to_status(error_name: str, error_msg: str) -> int:
    """Map YouTube transcript API errors to HTTP status codes."""
    error_map = {
        "TranscriptsDisabled": 422,
        "AgeRestricted": 422,
        "VideoUnplayable": 422,
        "VideoUnavailable": 404,
        "InvalidVideoId": 400,
        "NoTranscriptFound": 404,
        "RequestBlocked": 503,
        "IpBlocked": 503,
        "TooManyRequests": 503,
        "YouTubeDataUnparsable": 503,
        "YouTubeRequestFailed": 503,
    }

    if error_name in error_map:
        return error_map[error_name]

    if "transcript" in error_msg.lower() and "not found" in error_msg.lower():
        return 404

    return 500


async def fetch_transcript_with_retry(
    video_id: str, languages: list[str] | None = None
) -> dict:
    """Fetch transcript with retry logic for transient errors.

    Retries up to MAX_RETRIES times with exponential backoff for transient errors.
    Permanent errors (TranscriptsDisabled, AgeRestricted, etc.) are not retried.
    """
    last_result = None

    for attempt in range(MAX_RETRIES):
        result = await fetch_transcript(video_id, languages)

        if result["success"]:
            return result

        last_result = result

        if not result.get("retryable", False):
            return result

        if attempt < MAX_RETRIES - 1:
            delay = RETRY_DELAY_SECONDS * (2 ** attempt)
            logger.info(
                "Retrying transcript fetch for %s (attempt %d/%d) after %ds delay",
                video_id, attempt + 1, MAX_RETRIES, delay
            )
            await asyncio.sleep(delay)

    return last_result


def raise_for_transcript_error(result: dict, video_id: str) -> None:
    """Raise HTTPException if transcript fetch failed.

    Maps YouTube API errors to appropriate HTTP status codes and messages.
    """
    if result["success"]:
        return

    error_name = result.get("error_name", "")
    error_msg = result.get("error", "Unknown error")
    status_code = result.get("status_code", 500)

    error_messages = {
        "TranscriptsDisabled": "Transcripts are disabled for this video",
        "AgeRestricted": "This video is age-restricted by YouTube. Transcript access requires a signed-in YouTube session, which is not supported",
        "VideoUnplayable": "This video is unplayable (possibly region-locked)",
        "VideoUnavailable": "This video is unavailable (deleted or private)",
        "InvalidVideoId": "Invalid YouTube video ID",
        "NoTranscriptFound": "No transcript found in the requested language(s)",
        "RequestBlocked": "YouTube is temporarily blocking requests. Please try again later",
        "IpBlocked": "YouTube is temporarily blocking this server's IP. Please try again later",
        "TooManyRequests": "Too many requests to YouTube. Please try again later",
        "YouTubeDataUnparsable": "YouTube returned unparseable data. Please try again later",
        "YouTubeRequestFailed": "YouTube request failed. Please try again later",
    }

    detail = error_messages.get(error_name, f"Failed to fetch transcript: {error_msg}")

    raise HTTPException(status_code=status_code, detail=detail)

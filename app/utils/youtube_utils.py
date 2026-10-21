import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

ALLOWED_YOUTUBE_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

VIDEO_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(url: str) -> str | None:
    """Extract 11-character video ID from various YouTube URL formats.

    Supported formats:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/live/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID
    - Bare VIDEO_ID (11 characters)

    Returns:
        Video ID if valid, None otherwise
    """
    if not url:
        return None

    if VIDEO_ID_PATTERN.match(url):
        return url

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if not parsed.scheme or not parsed.netloc:
        return None

    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_YOUTUBE_DOMAINS:
        return None

    path = parsed.path
    query_params = {}
    if parsed.query:
        for param in parsed.query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                query_params[key] = value

    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtube-nocookie.com", "www.youtube-nocookie.com"}:
        if path == "/watch" and "v" in query_params:
            video_id = query_params["v"]
            if VIDEO_ID_PATTERN.match(video_id):
                return video_id

        for prefix in ["/shorts/", "/embed/", "/live/", "/v/"]:
            if path.startswith(prefix):
                video_id = path[len(prefix) :].split("/")[0].split("?")[0]
                if VIDEO_ID_PATTERN.match(video_id):
                    return video_id

    elif hostname == "youtu.be":
        video_id = path.lstrip("/").split("/")[0].split("?")[0]
        if VIDEO_ID_PATTERN.match(video_id):
            return video_id

    return None


def validate_youtube_url(url: str) -> tuple[bool, str, str | None]:
    """Validate YouTube URL and extract video ID.

    Returns:
        Tuple of (is_valid, error_message, video_id)
    """
    if not url or not url.strip():
        return False, "URL is required", None

    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format", None

    if parsed.scheme not in ("http", "https", ""):
        return False, "URL must use http or https scheme", None

    if not parsed.netloc:
        return False, "URL must include domain", None

    hostname = parsed.netloc.lower()
    if hostname not in ALLOWED_YOUTUBE_DOMAINS:
        return False, "URL must be from YouTube", None

    video_id = extract_video_id(url)
    if not video_id:
        return False, "Could not extract valid video ID from URL", None

    return True, "", video_id


class YouTubeURLRequest(BaseModel):
    """Request model for YouTube URL ingestion."""

    url: str
    languages: list[str] = Field(default_factory=lambda: ["en"])
    project_name: str | None = Field(default=None)
    file_name: str | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        is_valid, error, _ = validate_youtube_url(v)
        if not is_valid:
            raise ValueError(error)
        return v

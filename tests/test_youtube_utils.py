import pytest
from pydantic import ValidationError

from app.utils.youtube_utils import (
    YouTubeURLRequest,
    extract_video_id,
    validate_youtube_url,
)


class TestExtractVideoId:
    def test_watch_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_watch_url_with_extra_params(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42") == "dQw4w9WgXcQ"

    def test_youtu_be_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_live_url(self):
        assert extract_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_v_url(self):
        assert extract_video_id("https://www.youtube.com/v/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_mobile_url(self):
        assert extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_empty_string(self):
        assert extract_video_id("") is None

    def test_none_like_empty(self):
        assert extract_video_id("") is None

    def test_non_youtube_url(self):
        assert extract_video_id("https://example.com/video") is None

    def test_youtube_fake_domain(self):
        assert extract_video_id("https://youtube.com.fake.com/watch?v=dQw4w9WgXcQ") is None

    def test_short_id(self):
        assert extract_video_id("abc") is None

    def test_id_too_long(self):
        assert extract_video_id("abcdefghijkl") is None

    def test_special_chars_in_id(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQ_-4w9gXcQ") == "dQ_-4w9gXcQ"

    def test_nocookie_domain(self):
        assert extract_video_id("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


class TestValidateYoutubeUrl:
    def test_valid_watch(self):
        is_valid, error, vid = validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert is_valid
        assert error == ""
        assert vid == "dQw4w9WgXcQ"

    def test_valid_youtu_be(self):
        is_valid, _, vid = validate_youtube_url("https://youtu.be/dQw4w9WgXcQ")
        assert is_valid
        assert vid == "dQw4w9WgXcQ"

    def test_empty_url(self):
        is_valid, error, vid = validate_youtube_url("")
        assert not is_valid
        assert "required" in error.lower()
        assert vid is None

    def test_non_youtube_domain(self):
        is_valid, error, _ = validate_youtube_url("https://example.com/video")
        assert not is_valid
        assert "youtube" in error.lower()

    def test_fake_domain(self):
        is_valid, _error, _ = validate_youtube_url("https://youtube.com.fake.com/watch?v=dQw4w9WgXcQ")
        assert not is_valid

    def test_javascript_scheme(self):
        is_valid, error, _ = validate_youtube_url("javascript:alert(1)")
        assert not is_valid
        assert "scheme" in error.lower() or "youtube" in error.lower()

    def test_ftp_scheme(self):
        is_valid, error, _ = validate_youtube_url("ftp://youtube.com/watch?v=dQw4w9WgXcQ")
        assert not is_valid
        assert "scheme" in error.lower()

    def test_no_scheme_still_valid(self):
        is_valid, _, _ = validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert is_valid


class TestYouTubeURLRequest:
    def test_valid_request(self):
        req = YouTubeURLRequest(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert req.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert req.languages == ["en"]

    def test_custom_languages(self):
        req = YouTubeURLRequest(
            url="https://youtu.be/dQw4w9WgXcQ",
            languages=["es", "fr"],
        )
        assert req.languages == ["es", "fr"]

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationError):
            YouTubeURLRequest(url="https://example.com/video")

    def test_empty_url_raises(self):
        with pytest.raises(ValidationError):
            YouTubeURLRequest(url="")

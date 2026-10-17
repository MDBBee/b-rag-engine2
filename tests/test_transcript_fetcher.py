from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.utils.transcript_fetcher import (
    _is_retryable,
    _map_error_to_status,
    fetch_transcript,
    fetch_transcript_with_retry,
    raise_for_transcript_error,
)


class TestIsRetryable:
    def test_request_blocked_is_retryable(self):
        assert _is_retryable("RequestBlocked") is True

    def test_ip_blocked_is_retryable(self):
        assert _is_retryable("IpBlocked") is True

    def test_transcripts_disabled_not_retryable(self):
        assert _is_retryable("TranscriptsDisabled") is False

    def test_age_restricted_not_retryable(self):
        assert _is_retryable("AgeRestricted") is False

    def test_unknown_error_not_retryable(self):
        assert _is_retryable("UnknownError") is False


class TestMapErrorToStatus:
    def test_transcripts_disabled(self):
        assert _map_error_to_status("TranscriptsDisabled", "") == 422

    def test_age_restricted(self):
        assert _map_error_to_status("AgeRestricted", "") == 422

    def test_video_unavailable(self):
        assert _map_error_to_status("VideoUnavailable", "") == 404

    def test_video_unplayable(self):
        assert _map_error_to_status("VideoUnplayable", "") == 422

    def test_request_blocked(self):
        assert _map_error_to_status("RequestBlocked", "") == 503

    def test_unknown_error(self):
        assert _map_error_to_status("UnknownError", "") == 500

    def test_transcript_not_found_in_message(self):
        assert _map_error_to_status("SomeError", "Transcript not found for video") == 404


class TestFetchTranscript:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_snippet = MagicMock(text="Hello world")
        mock_transcript = MagicMock()
        mock_transcript.language_code = "en"
        mock_transcript.snippets = [mock_snippet]

        with patch("app.utils.transcript_fetcher.YouTubeTranscriptApi") as mock_api_cls:
            mock_instance = MagicMock()
            mock_instance.fetch.return_value = mock_transcript
            mock_api_cls.return_value = mock_instance

            result = await fetch_transcript("dQw4w9WgXcQ", ["en"])

            assert result["success"] is True
            assert result["video_id"] == "dQw4w9WgXcQ"
            assert result["language"] == "en"
            assert isinstance(result["full_text"], str)

    @pytest.mark.asyncio
    async def test_permanent_error_not_retried(self):
        with patch("app.utils.transcript_fetcher.YouTubeTranscriptApi") as mock_api_cls:
            mock_instance = MagicMock()

            class FakeTranscriptsDisabled(Exception):
                pass
            FakeTranscriptsDisabled.__name__ = "TranscriptsDisabled"

            mock_instance.fetch.side_effect = FakeTranscriptsDisabled("disabled")
            mock_api_cls.return_value = mock_instance

            result = await fetch_transcript("dQw4w9WgXcQ", ["en"])

            assert result["success"] is False
            assert result["retryable"] is False


class TestFetchTranscriptWithRetry:
    @pytest.mark.asyncio
    async def test_retries_transient_errors(self):
        call_count = 0

        async def mock_fetch(video_id, languages=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {
                    "success": False,
                    "error": "Blocked",
                    "error_name": "RequestBlocked",
                    "retryable": True,
                    "status_code": 503,
                }
            return {
                "success": True,
                "video_id": video_id,
                "language": "en",
                "full_text": "transcript text",
                "segment_count": 1,
            }

        with (
            patch("app.utils.transcript_fetcher.fetch_transcript", side_effect=mock_fetch),
            patch("app.utils.transcript_fetcher.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await fetch_transcript_with_retry("dQw4w9WgXcQ", ["en"])

            assert result["success"] is True
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_permanent_error(self):
        call_count = 0

        async def mock_fetch(video_id, languages=None):
            nonlocal call_count
            call_count += 1
            return {
                "success": False,
                "error": "Transcripts disabled",
                "error_name": "TranscriptsDisabled",
                "retryable": False,
                "status_code": 422,
            }

        with patch("app.utils.transcript_fetcher.fetch_transcript", side_effect=mock_fetch):
            result = await fetch_transcript_with_retry("dQw4w9WgXcQ", ["en"])

            assert result["success"] is False
            assert call_count == 1


class TestRaiseForTranscriptError:
    def test_success_does_not_raise(self):
        result = {"success": True, "full_text": "text"}
        raise_for_transcript_error(result, "abc")

    def test_transcripts_disabled_raises_422(self):
        result = {
            "success": False,
            "error_name": "TranscriptsDisabled",
            "error": "disabled",
            "status_code": 422,
        }
        with pytest.raises(HTTPException) as exc_info:
            raise_for_transcript_error(result, "abc")
        assert exc_info.value.status_code == 422

    def test_video_unavailable_raises_404(self):
        result = {
            "success": False,
            "error_name": "VideoUnavailable",
            "error": "unavailable",
            "status_code": 404,
        }
        with pytest.raises(HTTPException) as exc_info:
            raise_for_transcript_error(result, "abc")
        assert exc_info.value.status_code == 404

    def test_ip_blocked_raises_503(self):
        result = {
            "success": False,
            "error_name": "IpBlocked",
            "error": "blocked",
            "status_code": 503,
        }
        with pytest.raises(HTTPException) as exc_info:
            raise_for_transcript_error(result, "abc")
        assert exc_info.value.status_code == 503

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


class TestValidateVideo:
    def test_requires_auth(self):
        app.dependency_overrides.clear()
        client = TestClient(app)
        response = client.post(
            "/validate/video",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert response.status_code == 401

    def test_invalid_url_returns_422(self, client):
        response = client.post(
            "/validate/video",
            json={"url": "https://example.com/video"},
        )
        assert response.status_code == 422

    def test_success(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "video_id": "dQw4w9WgXcQ",
                "language": "en",
                "full_text": "Test transcript",
                "segment_count": 5,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert data["video_id"] == "dQw4w9WgXcQ"

    def test_transcript_disabled_returns_422(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error_name": "TranscriptsDisabled",
                "error": "disabled",
                "retryable": False,
                "status_code": 422,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 422
            assert "Transcripts are disabled" in response.json()["detail"]

    def test_video_unavailable_returns_404(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error_name": "VideoUnavailable",
                "error": "unavailable",
                "retryable": False,
                "status_code": 404,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 404
            assert "unavailable" in response.json()["detail"].lower()

    def test_age_restricted_returns_422(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error_name": "AgeRestricted",
                "error": "age-restricted",
                "retryable": False,
                "status_code": 422,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 422
            assert "age-restricted" in response.json()["detail"]

    def test_ip_blocked_returns_503(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error_name": "IpBlocked",
                "error": "blocked",
                "retryable": True,
                "status_code": 503,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 503

    def test_no_transcript_found_returns_404(self, client):
        with patch(
            "app.routers.validate.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value={
                "success": False,
                "error_name": "NoTranscriptFound",
                "error": "no transcript",
                "retryable": False,
                "status_code": 404,
            },
        ):
            response = client.post(
                "/validate/video",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 404
            assert "No transcript found" in response.json()["detail"]

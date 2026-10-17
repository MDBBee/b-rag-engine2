from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.typing.schemas import ChunkData, SummarizedChunk


def _mock_transcript_result(video_id="dQw4w9WgXcQ"):
    return {
        "success": True,
        "video_id": video_id,
        "language": "en",
        "full_text": "This is a test transcript with enough content to be chunked properly.",
        "segment_count": 5,
    }


def _mock_ingestion_result():
    return (
        3,
        "youtube",
        0,
        0,
        [ChunkData(text="chunk text", types=["text"])],
        [SummarizedChunk(page_content="chunk text", metadata={})],
    )


class TestVideoIdToCollectionName:
    def test_normal_id(self):
        from app.routers.youtube_ingest import video_id_to_collection_name
        result = video_id_to_collection_name("dQw4w9WgXcQ")
        assert result == "yt_dqw4w9wgxcq"

    def test_long_id_truncated(self):
        from app.routers.youtube_ingest import video_id_to_collection_name
        result = video_id_to_collection_name("abcdefghijklm")
        assert len(result) <= 40


class TestIngestYoutube:
    def test_requires_auth(self):
        app.dependency_overrides.clear()
        client = TestClient(app)
        response = client.post(
            "/ingest/youtube",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert response.status_code == 401

    def test_invalid_url_returns_422(self, client):
        response = client.post(
            "/ingest/youtube",
            json={"url": "https://example.com/video"},
        )
        assert response.status_code == 422

    def test_success(self, client):
        with patch(
            "app.routers.youtube_ingest.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value=_mock_transcript_result(),
        ), patch(
            "app.routers.youtube_ingest.ingestion_pipeline",
            new_callable=AsyncMock,
            return_value=_mock_ingestion_result(),
        ):
            response = client.post(
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["document_type"] == "youtube"

    def test_transcript_disabled_returns_422(self, client):
        with patch(
            "app.routers.youtube_ingest.fetch_transcript_with_retry",
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
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 422

    def test_video_unavailable_returns_404(self, client):
        with patch(
            "app.routers.youtube_ingest.fetch_transcript_with_retry",
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
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 404

    def test_ip_blocked_returns_503(self, client):
        with patch(
            "app.routers.youtube_ingest.fetch_transcript_with_retry",
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
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 503

    def test_collection_conflict_returns_409(self, client):
        with patch(
            "app.routers.youtube_ingest.fetch_transcript_with_retry",
            new_callable=AsyncMock,
            return_value=_mock_transcript_result(),
        ), patch(
            "app.routers.youtube_ingest.ingestion_pipeline",
            new_callable=AsyncMock,
            side_effect=ValueError("Collection already exists"),
        ):
            response = client.post(
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 409

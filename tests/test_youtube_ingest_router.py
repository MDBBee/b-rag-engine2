import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def _mock_transcript_result(video_id="dQw4w9WgXcQ"):
    return {
        "success": True,
        "video_id": video_id,
        "language": "en",
        "full_text": "This is a test transcript with enough content to be chunked properly.",
        "segment_count": 5,
    }


async def _mock_stream(*args, **kwargs):
    yield ("stage", {"stage": "partition"})
    yield ("done", {
        "status": "ok",
        "chunk_count": 3,
        "document_type": "youtube",
        "no_of_pages": 0,
        "first_chunk_index": 0,
        "last_chunk_index": 2,
        "chunks": [],
        "summarized_chunks": [],
    })


def _parse_sse_events(response_text):
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestVideoIdToCollectionName:
    def test_normal_id(self):
        from app.routers.youtube_ingest import video_id_to_project_name
        result = video_id_to_project_name("dQw4w9WgXcQ")
        assert result == "yt_dqw4w9wgxcq"

    def test_long_id_truncated(self):
        from app.routers.youtube_ingest import video_id_to_project_name
        result = video_id_to_project_name("abcdefghijklm")
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
            "app.routers.youtube_ingest.ingestion_pipeline_stream",
            side_effect=_mock_stream,
        ):
            response = client.post(
                "/ingest/youtube",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert response.status_code == 200
            events = _parse_sse_events(response.text)
            done_events = [e for e in events if e["type"] == "done"]
            assert len(done_events) == 1
            assert done_events[0]["document_type"] == "youtube"

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

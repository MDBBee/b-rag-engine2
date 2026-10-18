import json
from unittest.mock import patch

from app.main import app


async def _success_stream(*args, **kwargs):
    """Async generator yielding a successful ingestion sequence."""
    yield ("stage", {"stage": "partition"})
    yield ("progress", {"percent": 100, "stage": "partition"})
    yield ("stage", {"stage": "chunk"})
    yield ("progress", {"percent": 100, "stage": "chunk"})
    yield ("stage", {"stage": "vectorize"})
    yield ("progress", {"percent": 100, "stage": "vectorize"})
    yield ("done", {
        "status": "ok",
        "chunk_count": 5,
        "document_type": "pdf",
        "no_of_pages": 10,
        "first_chunk_index": 0,
        "last_chunk_index": 4,
        "chunks": [],
        "summarized_chunks": [],
    })


async def _error_stream(*args, **kwargs):
    """Async generator yielding an error event."""
    yield ("error", {"message": "Something went wrong"})


def _parse_sse_events(response_text):
    """Parse SSE response into list of event dicts."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_ingest_success(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline_stream", side_effect=_success_stream):
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["chunk_count"] == 5
        assert done_events[0]["document_type"] == "pdf"


def test_ingest_error_in_stream(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline_stream", side_effect=_error_stream):
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 200
        events = _parse_sse_events(response.text)
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "Something went wrong" in error_events[0]["message"]


def test_ingest_requires_auth():
    from fastapi.testclient import TestClient
    app.dependency_overrides.clear()
    client = TestClient(app)
    files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
    response = client.post("/ingest", files=files)
    assert response.status_code == 401

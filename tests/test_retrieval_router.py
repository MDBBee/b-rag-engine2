from unittest.mock import AsyncMock, patch

from app.main import app
from app.middleware.auth import get_current_user


def test_query_stream_success(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.retrieval.retrieval_pipeline") as mock_pipeline:
        async def mock_stream(*args, **kwargs):
            yield ("node_start", "router")
            yield ("token", "Hello")
            yield ("token", " world")
            yield ("done", None)
        mock_pipeline.side_effect = mock_stream
        payload = {
            "query": "What is this document about?",
            "collection_name": "test-collection"
        }
        response = client.post("/query/stream", json=payload)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]


def test_query_stream_with_messages(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.retrieval.retrieval_pipeline") as mock_pipeline:
        async def mock_stream(*args, **kwargs):
            yield ("token", "Answer")
            yield ("done", None)
        mock_pipeline.side_effect = mock_stream
        payload = {
            "query": "Follow up question",
            "collection_name": "test-collection",
            "messages": [{"role": "user", "content": "Previous question"}]
        }
        response = client.post("/query/stream", json=payload)
        assert response.status_code == 200


def test_query_stream_requires_auth():
    from fastapi.testclient import TestClient
    app.dependency_overrides.clear()
    client = TestClient(app)
    payload = {"query": "test", "collection_name": "test"}
    response = client.post("/query/stream", json=payload)
    assert response.status_code == 401

from unittest.mock import patch

from app.main import app


def test_ingest_success(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline") as mock_pipeline:
        mock_pipeline.return_value = (5, "pdf", 10, [], [])
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["chunk_count"] == 5
        assert data["document_type"] == "pdf"


def test_ingest_collection_conflict(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline") as mock_pipeline:
        mock_pipeline.side_effect = ValueError("Collection already exists")
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 409


def test_ingest_timeout(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline") as mock_pipeline:
        mock_pipeline.side_effect = TimeoutError()
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 504


def test_ingest_internal_error(client_with_user, mock_user):
    client = client_with_user(mock_user)
    with patch("app.routers.ingestion.ingestion_pipeline") as mock_pipeline:
        mock_pipeline.side_effect = Exception("Unexpected error")
        files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
        response = client.post("/ingest", files=files)
        assert response.status_code == 500


def test_ingest_requires_auth():
    from fastapi.testclient import TestClient
    app.dependency_overrides.clear()
    client = TestClient(app)
    files = {"file": ("test.pdf", b"%PDF-1.4\nfake pdf content")}
    response = client.post("/ingest", files=files)
    assert response.status_code == 401

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.middleware.auth import UserInfo, get_current_user


@pytest.fixture
def mock_user():
    """Mock user for testing authenticated endpoints."""
    return UserInfo(id="test-user-123", email="test@example.com", role="user")


@pytest.fixture
def admin_user():
    """Mock admin user for testing admin endpoints."""
    return UserInfo(id="admin-user-456", email="admin@example.com", role="admin")


@pytest.fixture
def client(mock_user):
    """Test client with auth bypassed."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_user():
    """Factory fixture to create client with specific user."""
    def _create_client(user):
        app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(app)
        return client
    return _create_client

import pytest
from fastapi import HTTPException
from jose import jwt

from app.config import settings
from app.middleware.auth import UserInfo, get_current_user, require_admin


def test_get_current_user_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = jwt.encode({"sub": "user-123", "email": "test@example.com", "role": "user"}, "test-secret", algorithm="HS256")
    user = get_current_user(authorization=f"Bearer {token}")
    assert user.id == "user-123"
    assert user.email == "test@example.com"
    assert user.role == "user"


def test_get_current_user_missing_header():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None)
    assert exc_info.value.status_code == 401


def test_get_current_user_invalid_scheme():
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Basic token123")
    assert exc_info.value.status_code == 401


def test_get_current_user_expired_token(monkeypatch):
    import time
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = jwt.encode({"sub": "user-123", "exp": int(time.time()) - 100}, "test-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_get_current_user_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = jwt.encode({"sub": "user-123"}, "wrong-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


def test_get_current_user_missing_sub():
    token = jwt.encode({"email": "test@example.com"}, "test-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


def test_get_current_user_default_role(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = jwt.encode({"sub": "user-123", "email": "test@example.com"}, "test-secret", algorithm="HS256")
    user = get_current_user(authorization=f"Bearer {token}")
    assert user.role == "user"


def test_require_admin_valid_admin():
    admin = UserInfo(id="admin-123", email="admin@example.com", role="admin")
    user = require_admin(user=admin)
    assert user.id == "admin-123"
    assert user.role == "admin"


def test_require_admin_regular_user():
    user = UserInfo(id="user-123", email="user@example.com", role="user")
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=user)
    assert exc_info.value.status_code == 403
    assert "admin" in exc_info.value.detail.lower()


def test_require_admin_subscriber():
    subscriber = UserInfo(id="sub-123", email="sub@example.com", role="subscriber")
    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=subscriber)
    assert exc_info.value.status_code == 403

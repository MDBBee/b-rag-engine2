import logging

from fastapi import Depends, Header, HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)


class UserInfo(BaseModel):
    id: str
    email: str
    role: str = "user"


def get_current_user(
    authorization: str | None = Header(None),
) -> UserInfo:
    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Auth failed: missing or invalid authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    token = authorization.split(" ", 1)[1]

    try:
        payload = jwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except ExpiredSignatureError:
        logger.warning("Auth failed: token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except JWTError as e:
        logger.warning("Auth failed: invalid token - %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user_id = payload.get("sub") or payload.get("id")
    if not user_id:
        logger.warning("Auth failed: invalid token payload (missing sub/id)")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    return UserInfo(
        id=str(user_id),
        email=str(payload.get("email", "")),
        role=str(payload.get("role", "user")),
    )


def require_admin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    if user.role != "admin":
        logger.warning(f"Auth failed: user {user.id} lacks admin role (has: {user.role})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

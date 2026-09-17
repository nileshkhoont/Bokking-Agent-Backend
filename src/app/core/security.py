from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def _create_token(subject: str, token_type: Literal["access", "refresh"], expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(admin_id: str) -> str:
    return _create_token(
        admin_id, "access", timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )


def create_refresh_token(admin_id: str) -> str:
    return _create_token(
        admin_id, "refresh", timedelta(minutes=settings.jwt_refresh_token_expire_minutes)
    )


def decode_token(token: str, expected_type: Literal["access", "refresh"] = "access") -> str:
    """Returns the admin_id (subject) if the token is valid and of the expected type."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise ValueError(f"Expected a {expected_type} token")

    subject = payload.get("sub")
    if not subject:
        raise ValueError("Token missing subject")
    return subject

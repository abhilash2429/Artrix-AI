"""API key hashing and JWT utilities."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of raw API key for storage."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, hashed_key)."""
    raw = f"{settings.api_key_prefix}{secrets.token_urlsafe(32)}"
    hashed = hash_api_key(raw)
    return raw, hashed


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Verify a raw API key against its stored hash."""
    return hash_api_key(raw_key) == stored_hash


def create_jwt_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT token with optional expiry."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_jwt_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises JWTError on failure."""
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )

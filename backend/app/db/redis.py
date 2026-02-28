"""Redis async client for session state, rate limiting, and short-term memory.

Provides helper methods wrapping raw Redis commands so callers never need
to handle redis.exceptions directly. All connection/command errors are
caught and re-raised as RedisConnectionError.
"""

from typing import Any

import structlog
from redis.asyncio import Redis
from redis.asyncio import from_url as redis_from_url
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import RedisConnectionError

logger = structlog.get_logger(__name__)

_client: Redis = redis_from_url(
    settings.redis_url,
    decode_responses=True,
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_redis() -> "RedisClient":
    """FastAPI dependency returning the singleton RedisClient wrapper."""
    return RedisClient(_client)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    logger.info("redis_shutdown")
    await _client.aclose()


# ---------------------------------------------------------------------------
# Helper wrapper
# ---------------------------------------------------------------------------

class RedisClient:
    """Thin wrapper over redis.asyncio.Redis with typed helpers.

    Every public method catches RedisError and re-raises as
    RedisConnectionError so the API layer gets a structured error.
    """

    def __init__(self, client: Redis) -> None:
        self._r = client

    @property
    def raw(self) -> Redis:
        """Escape hatch for advanced operations not covered by helpers."""
        return self._r

    async def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        """SET a key with an expiration (seconds)."""
        try:
            await self._r.setex(name=key, time=ttl_seconds, value=value)
        except RedisError as e:
            logger.error("redis_set_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis SET failed: {e}") from e

    async def get(self, key: str) -> str | None:
        """GET a key. Returns None if the key does not exist."""
        try:
            return await self._r.get(name=key)
        except RedisError as e:
            logger.error("redis_get_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis GET failed: {e}") from e

    async def delete(self, key: str) -> int:
        """DELETE a key. Returns the number of keys removed (0 or 1)."""
        try:
            return await self._r.delete(key)
        except RedisError as e:
            logger.error("redis_delete_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis DELETE failed: {e}") from e

    async def increment(self, key: str, amount: int = 1) -> int:
        """INCRBY a key. Creates the key with value 0 before incrementing if needed."""
        try:
            return await self._r.incrby(name=key, amount=amount)
        except RedisError as e:
            logger.error("redis_incr_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis INCRBY failed: {e}") from e

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Serialize value to JSON string and SET (optionally with TTL)."""
        import json
        payload = json.dumps(value)
        try:
            if ttl_seconds:
                await self._r.setex(name=key, time=ttl_seconds, value=payload)
            else:
                await self._r.set(name=key, value=payload)
        except RedisError as e:
            logger.error("redis_set_json_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis SET JSON failed: {e}") from e

    async def get_json(self, key: str) -> Any | None:
        """GET a key and deserialize from JSON. Returns None if key missing."""
        import json
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("redis_json_decode_failed", key=key)
            return None

    async def lpush(self, key: str, value: str) -> int:
        """LPUSH a value onto a list."""
        try:
            return await self._r.lpush(key, value)
        except RedisError as e:
            logger.error("redis_lpush_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis LPUSH failed: {e}") from e

    async def lrange(self, key: str, start: int = 0, stop: int = -1) -> list[str]:
        """LRANGE — return list elements in [start, stop]."""
        try:
            return await self._r.lrange(name=key, start=start, end=stop)
        except RedisError as e:
            logger.error("redis_lrange_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis LRANGE failed: {e}") from e

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        """Set a TTL on an existing key. Returns True if key exists."""
        try:
            return await self._r.expire(name=key, time=ttl_seconds)
        except RedisError as e:
            logger.error("redis_expire_failed", key=key, error=str(e))
            raise RedisConnectionError(f"Redis EXPIRE failed: {e}") from e

"""Conversation memory management.

Uses ConversationBufferWindowMemory (last 10 turns).
Persisted to Redis keyed by session_id.
On session end, cleared from Redis.

Serialization uses LangChain's message_to_dict / messages_from_dict —
no custom serialization logic.
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
)

from app.core.config import settings
from app.db.redis import RedisClient

logger = structlog.get_logger(__name__)


class ConversationMemoryManager:
    """Manages conversation memory per session using Redis.

    Window size is 10 turns — not configurable per tenant in Phase 1.
    """

    def __init__(self, redis: RedisClient, window_size: int = 10) -> None:
        self._redis = redis
        self._window_size = window_size

    def _key(self, session_id: UUID) -> str:
        return f"memory:{session_id}"

    def _ttl(self) -> int:
        return settings.idle_session_timeout_minutes * 60

    async def load(self, session_id: UUID) -> ConversationBufferWindowMemory:
        """Load conversation memory from Redis for a session.

        Deserializes from Redis JSON if exists.
        Returns a fresh ConversationBufferWindowMemory(k=window_size) on miss.
        """
        memory = ConversationBufferWindowMemory(
            k=self._window_size,
            return_messages=True,
            memory_key="chat_history",
        )

        raw = await self._redis.get(self._key(session_id))
        if raw is None:
            logger.debug("memory_cache_miss", session_id=str(session_id))
            return memory

        try:
            message_dicts: list[dict] = json.loads(raw)
            messages: list[BaseMessage] = messages_from_dict(message_dicts)
            for msg in messages:
                memory.chat_memory.add_message(msg)
            logger.debug(
                "memory_loaded",
                session_id=str(session_id),
                message_count=len(messages),
            )
        except Exception as e:
            logger.warning(
                "memory_deserialize_failed",
                session_id=str(session_id),
                error=str(e),
            )

        return memory

    async def save(
        self, session_id: UUID, memory: ConversationBufferWindowMemory
    ) -> None:
        """Serialize memory messages to JSON and store in Redis with TTL."""
        try:
            message_dicts = [
                message_to_dict(m) for m in memory.chat_memory.messages
            ]
            payload = json.dumps(message_dicts)
            await self._redis.set_with_ttl(
                self._key(session_id),
                payload,
                self._ttl(),
            )
            logger.debug(
                "memory_saved",
                session_id=str(session_id),
                message_count=len(message_dicts),
            )
        except Exception as e:
            logger.warning(
                "memory_save_failed",
                session_id=str(session_id),
                error=str(e),
            )

    async def clear(self, session_id: UUID) -> None:
        """Delete memory from Redis. Called on session end and escalation."""
        await self._redis.delete(self._key(session_id))
        logger.debug("memory_cleared", session_id=str(session_id))

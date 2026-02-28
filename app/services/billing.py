"""Conversation metering / billing service.

Every conversation is billed as one unit from session_start to session_end or escalation.
Counters accumulate in Redis during the session, then flush to Postgres billing_events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis import RedisClient
from app.models.billing import BillingEvent
from app.models.session import Session

logger = structlog.get_logger(__name__)


class BillingService:
    """Tracks token usage and generates billing events."""

    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self._db = db
        self._redis = redis

    def _key_input_tokens(self, session_id: UUID) -> str:
        return f"billing:{session_id}:input_tokens"

    def _key_output_tokens(self, session_id: UUID) -> str:
        return f"billing:{session_id}:output_tokens"

    def _key_message_count(self, session_id: UUID) -> str:
        return f"billing:{session_id}:message_count"

    def _ttl(self) -> int:
        """Double the session timeout as safety margin."""
        return settings.idle_session_timeout_minutes * 60 * 2

    async def record_message(
        self,
        session_id: UUID,
        tenant_id: UUID,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Increment running counters in Redis for a session."""
        ttl = self._ttl()

        await self._redis.increment(
            self._key_input_tokens(session_id), input_tokens
        )
        await self._redis.increment(
            self._key_output_tokens(session_id), output_tokens
        )
        await self._redis.increment(self._key_message_count(session_id), 1)

        # Refresh TTL on all keys
        await self._redis.expire(self._key_input_tokens(session_id), ttl)
        await self._redis.expire(self._key_output_tokens(session_id), ttl)
        await self._redis.expire(self._key_message_count(session_id), ttl)

        logger.debug(
            "billing_message_recorded",
            session_id=str(session_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def close_session(
        self,
        session_id: UUID,
        tenant_id: UUID,
        event_type: str,
    ) -> None:
        """Flush session counters from Redis to billing_events table in Postgres.

        event_type: 'resolved' | 'escalated' | 'timeout'
        This is the billable event.
        """
        # 1. Read counters from Redis
        raw_input = await self._redis.get(self._key_input_tokens(session_id))
        raw_output = await self._redis.get(
            self._key_output_tokens(session_id)
        )
        raw_count = await self._redis.get(
            self._key_message_count(session_id)
        )

        total_input = int(raw_input) if raw_input else 0
        total_output = int(raw_output) if raw_output else 0
        total_messages = int(raw_count) if raw_count else 0

        if raw_input is None and raw_output is None and raw_count is None:
            logger.warning(
                "billing_redis_keys_missing",
                session_id=str(session_id),
                event_type=event_type,
            )

        # 2. Insert billing event
        event = BillingEvent(
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=event_type,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_messages=total_messages,
        )
        self._db.add(event)
        await self._db.flush()

        # 3. Delete Redis keys
        await self._redis.delete(self._key_input_tokens(session_id))
        await self._redis.delete(self._key_output_tokens(session_id))
        await self._redis.delete(self._key_message_count(session_id))

        logger.info(
            "billing_session_closed",
            session_id=str(session_id),
            tenant_id=str(tenant_id),
            event_type=event_type,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_messages=total_messages,
        )

    async def auto_close_idle_sessions(self) -> None:
        """Close sessions idle beyond the timeout threshold.

        Queries sessions where status='active' and started_at is older
        than IDLE_SESSION_TIMEOUT_MINUTES. For each, calls close_session
        with event_type='timeout'. Called by the background cleanup task.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            minutes=settings.idle_session_timeout_minutes
        )

        result = await self._db.execute(
            select(Session).where(
                Session.status == "active",
                Session.started_at < cutoff,
            )
        )
        idle_sessions = result.scalars().all()

        closed_count = 0
        for session in idle_sessions:
            try:
                await self._db.execute(
                    update(Session)
                    .where(Session.id == session.id)
                    .values(
                        status="resolved",
                        ended_at=datetime.now(timezone.utc),
                    )
                )
                await self._db.flush()

                await self.close_session(
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    event_type="timeout",
                )
                closed_count += 1
            except Exception as e:
                logger.error(
                    "billing_auto_close_failed",
                    session_id=str(session.id),
                    error=str(e),
                )

        if closed_count > 0:
            logger.info(
                "billing_idle_sessions_closed",
                count=closed_count,
            )

"""Escalation trigger logic and webhook firing.

Escalation thresholds from Section 7.3 of agents.md.
Webhook POST is non-blocking (background task) with 3 retries + exponential backoff.

EscalationService.escalate() does exactly these things in order:
1. Load full transcript from Postgres messages table
2. Set sessions.status = 'escalated', sessions.escalation_reason, sessions.ended_at
3. Fire webhook as non-blocking background task (if URL configured)
4. Clear memory from Redis
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import BillingEvent
from app.models.message import Message
from app.models.session import Session
from app.services.agent.memory import ConversationMemoryManager

logger = structlog.get_logger(__name__)


THRESHOLDS = {
    "auto_resolve": 0.80,
    "low_confidence": 0.55,
    "escalate": 0.55,
}


def should_escalate(
    confidence: float,
    turn_count: int,
    max_turns: int,
) -> tuple[bool, str | None]:
    """Determine if the conversation should be escalated to a human agent."""
    if confidence < THRESHOLDS["escalate"]:
        return True, "low_retrieval_confidence"
    if turn_count >= max_turns:
        return True, "max_turns_exceeded"
    return False, None


class EscalationService:
    """Handles escalation webhook firing and session status updates."""

    def __init__(
        self,
        db: AsyncSession,
        memory_manager: ConversationMemoryManager,
    ) -> None:
        self._db = db
        self._memory_manager = memory_manager

    async def escalate(
        self,
        session_id: UUID,
        tenant_id: UUID,
        reason: str,
        last_user_message: str,
        webhook_url: str | None,
        external_user_id: str | None,
    ) -> None:
        """Execute the full escalation flow.

        Steps (in exact order):
        1. Load full transcript from Postgres messages table
        2. Set session status to 'escalated' with reason and ended_at
        3. Fire webhook as non-blocking background task (if URL configured)
        4. Clear memory from Redis
        """
        # 1. Load transcript
        result = await self._db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        messages = result.scalars().all()
        transcript = [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
            }
            for msg in messages
        ]

        # 2. Update session status
        await self._db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(
                status="escalated",
                escalation_reason=reason,
                ended_at=datetime.now(timezone.utc),
            )
        )
        await self._db.commit()

        # 3. Fire webhook (non-blocking via asyncio.create_task)
        if webhook_url is not None:
            payload = {
                "event": "escalation",
                "session_id": str(session_id),
                "tenant_id": str(tenant_id),
                "external_user_id": external_user_id,
                "escalation_reason": reason,
                "transcript": transcript,
                "last_user_message": last_user_message,
                "escalated_at": datetime.now(timezone.utc).isoformat(),
            }
            asyncio.create_task(
                self._fire_webhook_with_retries(
                    webhook_url=webhook_url,
                    payload=payload,
                    session_id=session_id,
                    tenant_id=tenant_id,
                )
            )

        # 4. Clear memory from Redis
        await self._memory_manager.clear(session_id)

        logger.info(
            "escalation_complete",
            session_id=str(session_id),
            tenant_id=str(tenant_id),
            reason=reason,
            webhook_configured=webhook_url is not None,
        )

    async def _fire_webhook_with_retries(
        self,
        webhook_url: str,
        payload: dict[str, Any],
        session_id: UUID,
        tenant_id: UUID,
        max_retries: int = 3,
    ) -> None:
        """Fire escalation webhook with exponential backoff retries.

        Retry delays: 1s, 2s, 4s.
        On all 3 failures: log error, insert billing_event with
        event_type='escalation_webhook_failed'.

        Runs as background task — entire method wrapped in top-level
        try/except so exceptions are never propagated to the event loop.
        """
        try:
            backoff_seconds = [1, 2, 4]

            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.post(
                            webhook_url,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                        )
                        response.raise_for_status()

                    logger.info(
                        "escalation_webhook_sent",
                        session_id=str(session_id),
                        status_code=response.status_code,
                        attempt=attempt + 1,
                    )
                    return  # Success

                except Exception as e:
                    logger.warning(
                        "escalation_webhook_attempt_failed",
                        session_id=str(session_id),
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(backoff_seconds[attempt])

            # All retries exhausted
            logger.error(
                "escalation_webhook_all_retries_failed",
                session_id=str(session_id),
                tenant_id=str(tenant_id),
                webhook_url=webhook_url,
            )

            # Insert billing event for failed webhook — needs its own db session
            # since the request session may be closed by now
            try:
                from app.db.postgres import async_session_factory

                async with async_session_factory() as db:
                    failed_event = BillingEvent(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        event_type="escalation_webhook_failed",
                        total_input_tokens=0,
                        total_output_tokens=0,
                        total_messages=0,
                    )
                    db.add(failed_event)
                    await db.commit()
            except Exception as db_err:
                logger.error(
                    "escalation_webhook_failed_billing_insert_error",
                    error=str(db_err),
                )
        except Exception as e:
            logger.error(
                "escalation_webhook_task_error",
                session_id=str(session_id),
                tenant_id=str(tenant_id),
                error=str(e),
            )

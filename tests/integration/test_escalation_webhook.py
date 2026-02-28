"""Integration tests for escalation webhook.

Tests:
  - Webhook fires when escalation triggered
  - Webhook payload matches Section 7.4 schema
  - On webhook failure: billing_event with event_type='escalation_webhook_failed' inserted
  - Webhook failure does not raise or affect the agent response
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.agent.escalation import EscalationService


def _make_mock_db(messages: list | None = None) -> MagicMock:
    """Create a mock async DB session."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    # Mock query result for messages
    mock_msgs = messages or []
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_msgs
    db.execute = AsyncMock(return_value=mock_result)

    return db


def _make_mock_memory() -> MagicMock:
    """Create a mock ConversationMemoryManager."""
    mem = MagicMock()
    mem.clear = AsyncMock()
    return mem


def _make_mock_message(role: str, content: str) -> MagicMock:
    """Create a mock Message ORM object."""
    msg = MagicMock()
    msg.role = role
    msg.content = content
    msg.created_at = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return msg


class TestEscalationWebhookFires:
    """Tests that webhook fires correctly on escalation."""

    @pytest.mark.asyncio
    async def test_webhook_fires_on_escalation(self) -> None:
        """Webhook should POST to the configured URL on escalation."""
        messages = [
            _make_mock_message("user", "I need help with my order"),
            _make_mock_message("assistant", "Could you provide your order number?"),
        ]
        db = _make_mock_db(messages)
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        session_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        with patch("app.services.agent.escalation.asyncio.create_task") as mock_task:
            await svc.escalate(
                session_id=session_id,
                tenant_id=tenant_id,
                reason="low_retrieval_confidence",
                last_user_message="I need help",
                webhook_url="https://example.com/webhook",
                external_user_id="user-123",
            )

            # Verify create_task was called (webhook fires in background)
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_escalation_without_webhook_url(self) -> None:
        """Escalation without webhook URL should not fire webhook."""
        db = _make_mock_db([])
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        with patch("app.services.agent.escalation.asyncio.create_task") as mock_task:
            await svc.escalate(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                reason="low_retrieval_confidence",
                last_user_message="help",
                webhook_url=None,
                external_user_id=None,
            )

            mock_task.assert_not_called()


class TestWebhookPayloadSchema:
    """Tests that webhook payload matches Section 7.4 schema."""

    @pytest.mark.asyncio
    async def test_webhook_payload_matches_spec(self) -> None:
        """Payload should contain all required fields from Section 7.4.

        Validates the actual payload passed to _fire_webhook_with_retries,
        not a locally constructed dict.
        """
        messages = [
            _make_mock_message("user", "Help me"),
            _make_mock_message("assistant", "Sure, what do you need?"),
        ]
        db = _make_mock_db(messages)
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        session_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        with patch.object(
            svc, "_fire_webhook_with_retries", new_callable=AsyncMock
        ) as mock_fire:
            with patch("app.services.agent.escalation.asyncio.create_task"):
                await svc.escalate(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    reason="low_retrieval_confidence",
                    last_user_message="Help me",
                    webhook_url="https://example.com/hook",
                    external_user_id="user-456",
                )

            # Validate actual payload from the call arguments
            mock_fire.assert_called_once()
            kwargs = mock_fire.call_args.kwargs
            payload = kwargs["payload"]

            # All required fields per Section 7.4
            assert payload["event"] == "escalation"
            assert payload["session_id"] == str(session_id)
            assert payload["tenant_id"] == str(tenant_id)
            assert payload["external_user_id"] == "user-456"
            assert payload["escalation_reason"] == "low_retrieval_confidence"
            assert payload["last_user_message"] == "Help me"
            assert "escalated_at" in payload

            # Transcript matches messages
            assert isinstance(payload["transcript"], list)
            assert len(payload["transcript"]) == 2
            assert payload["transcript"][0]["role"] == "user"
            assert payload["transcript"][0]["content"] == "Help me"
            assert payload["transcript"][1]["role"] == "assistant"
            assert payload["transcript"][1]["content"] == "Sure, what do you need?"
            assert "timestamp" in payload["transcript"][0]


class TestWebhookFailureHandling:
    """Tests that webhook failure doesn't propagate errors."""

    @pytest.mark.asyncio
    async def test_webhook_failure_does_not_raise(self) -> None:
        """Webhook failures should be caught internally, not raise."""
        db = _make_mock_db([])
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        session_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Test _fire_webhook_with_retries directly with a failing URL
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_class.return_value = mock_client

            # Mock async_session_factory for the billing event insert
            mock_billing_session = MagicMock()
            mock_billing_session.add = MagicMock()
            mock_billing_session.commit = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_billing_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "app.db.postgres.async_session_factory",
                return_value=mock_ctx,
            ):
                # Should not raise — errors are caught internally
                await svc._fire_webhook_with_retries(
                    webhook_url="https://example.com/failing",
                    payload={"test": "data"},
                    session_id=session_id,
                    tenant_id=tenant_id,
                    max_retries=1,  # minimize test time
                )

    @pytest.mark.asyncio
    async def test_webhook_failure_inserts_billing_event(self) -> None:
        """On all retries exhausted, billing_event with
        event_type='escalation_webhook_failed' is inserted."""
        db = _make_mock_db([])
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        session_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Mock httpx to always fail
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_class.return_value = mock_client

            # Mock async_session_factory for the billing event insert
            mock_billing_session = MagicMock()
            mock_billing_session.add = MagicMock()
            mock_billing_session.commit = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_billing_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "app.db.postgres.async_session_factory",
                return_value=mock_ctx,
            ):
                await svc._fire_webhook_with_retries(
                    webhook_url="https://example.com/failing",
                    payload={"test": "data"},
                    session_id=session_id,
                    tenant_id=tenant_id,
                    max_retries=1,
                )

            # Verify billing event was inserted with correct event_type
            mock_billing_session.add.assert_called_once()
            billing_event = mock_billing_session.add.call_args[0][0]
            assert billing_event.event_type == "escalation_webhook_failed"
            assert billing_event.tenant_id == tenant_id
            assert billing_event.session_id == session_id
            assert billing_event.total_input_tokens == 0
            assert billing_event.total_output_tokens == 0
            assert billing_event.total_messages == 0

    @pytest.mark.asyncio
    async def test_escalation_completes_despite_webhook_failure(self) -> None:
        """Escalation should complete even if webhook fails."""
        messages = [_make_mock_message("user", "help")]
        db = _make_mock_db(messages)
        mem = _make_mock_memory()

        svc = EscalationService(db=db, memory_manager=mem)

        # Even with a webhook URL, escalation should complete
        with patch("app.services.agent.escalation.asyncio.create_task"):
            # Should not raise
            await svc.escalate(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                reason="low_retrieval_confidence",
                last_user_message="help",
                webhook_url="https://example.com/will-fail",
                external_user_id=None,
            )

        # Session status should have been updated
        assert db.execute.call_count >= 2  # SELECT messages + UPDATE session
        assert db.commit.called
        # Memory should have been cleared
        mem.clear.assert_called_once()

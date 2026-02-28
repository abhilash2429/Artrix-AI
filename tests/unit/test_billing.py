"""Unit tests for BillingService.

Tests:
  - record_message increments all three Redis counters
  - close_session reads counters, writes billing_event, deletes Redis keys
  - close_session with missing Redis keys inserts billing_event with 0 counts
  - auto_close_idle_sessions only closes sessions older than timeout threshold
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import MockRedisClient


# We need to mock the DB interactions
class MockBillingEvent:
    """Mock billing event for assertion."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestBillingRecordMessage:
    """Tests for BillingService.record_message()."""

    @pytest.mark.asyncio
    async def test_record_message_increments_counters(
        self, mock_redis: MockRedisClient
    ) -> None:
        """record_message should increment input, output, and message count."""
        from app.services.billing import BillingService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = BillingService(db=db, redis=mock_redis)  # type: ignore[arg-type]
        sid = uuid.uuid4()
        tid = uuid.uuid4()

        await svc.record_message(
            session_id=sid, tenant_id=tid, input_tokens=100, output_tokens=50
        )

        assert await mock_redis.get(f"billing:{sid}:input_tokens") == "100"
        assert await mock_redis.get(f"billing:{sid}:output_tokens") == "50"
        assert await mock_redis.get(f"billing:{sid}:message_count") == "1"

    @pytest.mark.asyncio
    async def test_record_message_accumulates(
        self, mock_redis: MockRedisClient
    ) -> None:
        """Multiple record_message calls should accumulate counters."""
        from app.services.billing import BillingService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = BillingService(db=db, redis=mock_redis)  # type: ignore[arg-type]
        sid = uuid.uuid4()
        tid = uuid.uuid4()

        await svc.record_message(sid, tid, 100, 50)
        await svc.record_message(sid, tid, 200, 100)

        assert await mock_redis.get(f"billing:{sid}:input_tokens") == "300"
        assert await mock_redis.get(f"billing:{sid}:output_tokens") == "150"
        assert await mock_redis.get(f"billing:{sid}:message_count") == "2"


class TestBillingCloseSession:
    """Tests for BillingService.close_session()."""

    @pytest.mark.asyncio
    async def test_close_session_reads_writes_deletes(
        self, mock_redis: MockRedisClient
    ) -> None:
        """close_session reads counters, writes billing_event, deletes keys."""
        from app.services.billing import BillingService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = BillingService(db=db, redis=mock_redis)  # type: ignore[arg-type]
        sid = uuid.uuid4()
        tid = uuid.uuid4()

        # Simulate existing counters
        await mock_redis.increment(f"billing:{sid}:input_tokens", 500)
        await mock_redis.increment(f"billing:{sid}:output_tokens", 200)
        await mock_redis.increment(f"billing:{sid}:message_count", 5)

        await svc.close_session(sid, tid, "resolved")

        # Verify billing event was added to DB
        assert db.add.call_count == 1
        event = db.add.call_args[0][0]
        assert event.tenant_id == tid
        assert event.session_id == sid
        assert event.event_type == "resolved"
        assert event.total_input_tokens == 500
        assert event.total_output_tokens == 200
        assert event.total_messages == 5

        # Verify Redis keys were deleted
        assert await mock_redis.get(f"billing:{sid}:input_tokens") is None
        assert await mock_redis.get(f"billing:{sid}:output_tokens") is None
        assert await mock_redis.get(f"billing:{sid}:message_count") is None

    @pytest.mark.asyncio
    async def test_close_session_missing_keys_zero_counts(
        self, mock_redis: MockRedisClient
    ) -> None:
        """close_session with missing Redis keys → billing_event with 0 counts."""
        from app.services.billing import BillingService

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = BillingService(db=db, redis=mock_redis)  # type: ignore[arg-type]
        sid = uuid.uuid4()
        tid = uuid.uuid4()

        # No Redis keys pre-set — they are missing
        await svc.close_session(sid, tid, "timeout")

        # Should still create billing event with 0 counts
        assert db.add.call_count == 1
        event = db.add.call_args[0][0]
        assert event.total_input_tokens == 0
        assert event.total_output_tokens == 0
        assert event.total_messages == 0
        assert event.event_type == "timeout"


class TestBillingAutoClose:
    """Tests for BillingService.auto_close_idle_sessions()."""

    @pytest.mark.asyncio
    async def test_auto_close_only_idle_sessions(
        self, mock_redis: MockRedisClient
    ) -> None:
        """auto_close should only close sessions older than timeout threshold."""
        from app.services.billing import BillingService

        # Create mock sessions
        old_session = MagicMock()
        old_session.id = uuid.uuid4()
        old_session.tenant_id = uuid.uuid4()
        old_session.status = "active"
        old_session.started_at = datetime.now(timezone.utc) - timedelta(minutes=60)

        # Mock DB
        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock the query to return old sessions
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [old_session]
        db.execute = AsyncMock(return_value=mock_result)

        svc = BillingService(db=db, redis=mock_redis)  # type: ignore[arg-type]

        await svc.auto_close_idle_sessions()

        # execute should have been called:
        # 1. SELECT idle sessions
        # 2. UPDATE session status
        # 3. get billing key reads (3 calls through close_session)
        assert db.execute.call_count >= 2

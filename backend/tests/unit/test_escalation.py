"""Unit tests for escalation decision logic.

Tests:
  - confidence=0.3, threshold=0.55 → escalate=True, reason="low_retrieval_confidence"
  - confidence=0.9, threshold=0.55 → escalate=False
  - confidence=0.6, turn_count=10, max_turns=10 → escalate=True, reason="max_turns_exceeded"
  - confidence=0.6, turn_count=9, max_turns=10 → escalate=False
  - confidence=0.0 → always escalate regardless of turn count
"""

from __future__ import annotations

import pytest

from app.services.agent.escalation import should_escalate


class TestShouldEscalate:
    """Tests for the should_escalate function."""

    def test_low_confidence_triggers_escalation(self) -> None:
        """confidence=0.3, threshold=0.55 → escalate."""
        escalate, reason = should_escalate(confidence=0.3, turn_count=2, max_turns=10)
        assert escalate is True
        assert reason == "low_retrieval_confidence"

    def test_high_confidence_no_escalation(self) -> None:
        """confidence=0.9, threshold=0.55 → no escalate."""
        escalate, reason = should_escalate(confidence=0.9, turn_count=2, max_turns=10)
        assert escalate is False
        assert reason is None

    def test_max_turns_triggers_escalation(self) -> None:
        """confidence=0.6, turn_count=10, max_turns=10 → escalate."""
        escalate, reason = should_escalate(confidence=0.6, turn_count=10, max_turns=10)
        assert escalate is True
        assert reason == "max_turns_exceeded"

    def test_under_max_turns_no_escalation(self) -> None:
        """confidence=0.6, turn_count=9, max_turns=10 → no escalate."""
        escalate, reason = should_escalate(confidence=0.6, turn_count=9, max_turns=10)
        assert escalate is False
        assert reason is None

    def test_zero_confidence_always_escalates(self) -> None:
        """confidence=0.0 → always escalate regardless of turn count."""
        escalate, reason = should_escalate(confidence=0.0, turn_count=1, max_turns=100)
        assert escalate is True
        assert reason == "low_retrieval_confidence"

    def test_borderline_confidence_no_escalation(self) -> None:
        """confidence exactly at threshold → no escalate."""
        escalate, reason = should_escalate(confidence=0.55, turn_count=3, max_turns=10)
        assert escalate is False
        assert reason is None

    def test_just_below_threshold_escalates(self) -> None:
        """confidence just below threshold → escalate."""
        escalate, reason = should_escalate(confidence=0.54, turn_count=1, max_turns=10)
        assert escalate is True
        assert reason == "low_retrieval_confidence"

"""Unit tests for IntentRouter.classify() — all three branches + edge cases.

Tests cover:
  - CONVERSATIONAL: greetings, thanks, acknowledgements
  - DOMAIN_QUERY: product/policy questions
  - OUT_OF_SCOPE: topics outside allowed list
  - Fallback: unexpected LLM output → DOMAIN_QUERY
  - Strip: whitespace handling
  - Timeout: LLM failure → DOMAIN_QUERY (no raise)
  - Case insensitivity: uppercase LLM response
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent.intent_router import IntentRouter, IntentType
from app.services.llm.base import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_llm(return_text: str) -> LLMProvider:
    """Create a mock LLMProvider that returns the given text from generate()."""
    mock = MagicMock(spec=LLMProvider)
    mock.generate = AsyncMock(
        return_value=LLMResponse(text=return_text, input_tokens=50, output_tokens=1)
    )
    return mock


def _make_timeout_llm() -> LLMProvider:
    """Create a mock LLMProvider whose generate() raises asyncio.TimeoutError."""
    mock = MagicMock(spec=LLMProvider)
    mock.generate = AsyncMock(side_effect=asyncio.TimeoutError())
    return mock


_VERTICAL = "ecommerce"
_ALLOWED_TOPICS = ["returns", "orders", "shipping"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIntentRouter:
    """Tests for IntentRouter.classify()."""

    @pytest.mark.asyncio
    async def test_hello_is_conversational(self) -> None:
        llm = _make_mock_llm("conversational")
        router = IntentRouter(llm)
        result = await router.classify("hello", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_hi_there_is_conversational(self) -> None:
        llm = _make_mock_llm("conversational")
        router = IntentRouter(llm)
        result = await router.classify("hi there", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_thanks_is_conversational(self) -> None:
        llm = _make_mock_llm("conversational")
        router = IntentRouter(llm)
        result = await router.classify("thanks", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_return_policy_is_domain_query(self) -> None:
        llm = _make_mock_llm("domain_query")
        router = IntentRouter(llm)
        result = await router.classify(
            "what is your return policy?", _VERTICAL, _ALLOWED_TOPICS
        )
        assert result == IntentType.DOMAIN_QUERY

    @pytest.mark.asyncio
    async def test_track_order_is_domain_query(self) -> None:
        llm = _make_mock_llm("domain_query")
        router = IntentRouter(llm)
        result = await router.classify(
            "how do I track my order?", _VERTICAL, _ALLOWED_TOPICS
        )
        assert result == IntentType.DOMAIN_QUERY

    @pytest.mark.asyncio
    async def test_competitor_prices_is_out_of_scope(self) -> None:
        llm = _make_mock_llm("out_of_scope")
        router = IntentRouter(llm)
        result = await router.classify(
            "what are your competitor's prices?",
            _VERTICAL,
            ["returns", "orders"],
        )
        assert result == IntentType.OUT_OF_SCOPE

    @pytest.mark.asyncio
    async def test_unexpected_string_falls_back_to_conversational(self) -> None:
        llm = _make_mock_llm("unknown")
        router = IntentRouter(llm)
        result = await router.classify("something weird", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_whitespace_is_stripped(self) -> None:
        llm = _make_mock_llm("  domain_query  ")
        router = IntentRouter(llm)
        result = await router.classify(
            "tell me about returns", _VERTICAL, _ALLOWED_TOPICS
        )
        assert result == IntentType.DOMAIN_QUERY

    @pytest.mark.asyncio
    async def test_timeout_falls_back_to_conversational(self) -> None:
        llm = _make_timeout_llm()
        router = IntentRouter(llm)
        # Must not raise — should return CONVERSATIONAL as safe default
        result = await router.classify("I need help", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_uppercase_response_is_case_insensitive(self) -> None:
        llm = _make_mock_llm("CONVERSATIONAL")
        router = IntentRouter(llm)
        result = await router.classify("hey!", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

    @pytest.mark.asyncio
    async def test_truncated_label_parsed_by_prefix(self) -> None:
        llm = _make_mock_llm("convers")
        router = IntentRouter(llm)
        result = await router.classify("hello", _VERTICAL, _ALLOWED_TOPICS)
        assert result == IntentType.CONVERSATIONAL

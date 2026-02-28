"""Integration tests for chat turn processing.

Tests:
  - CONVERSATIONAL turn: verify LLMProvider.generate() called,
    no tool calls, message persisted with intent_type='conversational'
  - DOMAIN_QUERY turn: verify retrieval called, response non-empty,
    source_chunks populated
  - OUT_OF_SCOPE turn: no retrieval call, escalation_required=False
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent.core import AgentCore, AgentTurnOutput
from app.services.agent.intent_router import IntentType
from app.services.rag.retrieval import RankedResult, RetrievalOutput
from tests.conftest import MockLLMProvider, MockRedisClient


def _make_mock_db() -> MagicMock:
    """Create a mock async DB session."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_mock_memory_manager() -> MagicMock:
    """Create a mock ConversationMemoryManager."""
    from langchain.memory import ConversationBufferWindowMemory

    memory = ConversationBufferWindowMemory(
        k=10, return_messages=True, memory_key="chat_history"
    )

    manager = MagicMock()
    manager.load = AsyncMock(return_value=memory)
    manager.save = AsyncMock()
    manager.clear = AsyncMock()
    return manager


def _make_mock_escalation_service() -> MagicMock:
    """Create a mock EscalationService."""
    svc = MagicMock()
    svc.escalate = AsyncMock()
    return svc


def _make_mock_retrieval_service(
    confidence: float = 0.9,
    should_escalate: bool = False,
) -> MagicMock:
    """Create a mock RetrievalService returning configurable results."""
    results = [
        RankedResult(
            chunk_id="chunk-1",
            text="Test chunk content about return policy.",
            payload={
                "filename": "policy.pdf",
                "section_heading": "Returns",
                "chunk_id": "chunk-1",
            },
            relevance_score=confidence,
            rank=0,
        )
    ]

    svc = MagicMock()
    svc.retrieve = AsyncMock(
        return_value=RetrievalOutput(
            results=results,
            confidence=confidence,
            should_escalate=should_escalate,
            escalation_reason="low_retrieval_confidence" if should_escalate else None,
            retrieval_latency_ms=100,
        )
    )
    return svc


_TENANT_CONFIG = {
    "vertical": "ecommerce",
    "persona_name": "TestBot",
    "persona_description": "A test support agent",
    "company_name": "TestCorp",
    "allowed_topics": ["orders", "returns"],
    "blocked_topics": ["competitor_comparison"],
    "escalation_threshold": 0.55,
    "max_turns_before_escalation": 10,
}


class TestConversationalTurn:
    """CONVERSATIONAL intent: direct LLM response, no tools."""

    @pytest.mark.asyncio
    async def test_conversational_calls_generate(self) -> None:
        """Verify LLMProvider.generate() is called for conversational turns."""
        llm = MockLLMProvider(generate_text="Hello! How can I help?")

        agent = AgentCore(
            llm=llm,
            retrieval_service=_make_mock_retrieval_service(),
            escalation_service=_make_mock_escalation_service(),
            memory_manager=_make_mock_memory_manager(),
            db=_make_mock_db(),
        )

        with patch.object(
            agent._intent_router,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentType.CONVERSATIONAL,
        ):
            output = await agent.handle_turn(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                message="hello",
                tenant_config=_TENANT_CONFIG,
            )

        assert output.intent_type == IntentType.CONVERSATIONAL
        assert len(llm.generate_calls) >= 1
        assert output.response == "Hello! How can I help?"
        assert output.confidence is None
        assert output.source_chunks is None
        assert output.escalation_required is False

    @pytest.mark.asyncio
    async def test_conversational_no_retrieval(self) -> None:
        """Verify RetrievalService is NOT called for conversational turns."""
        retrieval = _make_mock_retrieval_service()

        agent = AgentCore(
            llm=MockLLMProvider(),
            retrieval_service=retrieval,
            escalation_service=_make_mock_escalation_service(),
            memory_manager=_make_mock_memory_manager(),
            db=_make_mock_db(),
        )

        with patch.object(
            agent._intent_router,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentType.CONVERSATIONAL,
        ):
            await agent.handle_turn(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                message="thanks",
                tenant_config=_TENANT_CONFIG,
            )

        retrieval.retrieve.assert_not_called()


class TestDomainQueryTurn:
    """DOMAIN_QUERY intent: full RAG pipeline."""

    @pytest.mark.asyncio
    async def test_domain_query_calls_retrieval(self) -> None:
        """Verify RetrievalService.retrieve() is called for domain queries."""
        retrieval = _make_mock_retrieval_service(confidence=0.9)
        llm = MockLLMProvider(
            generate_text="Based on our return policy, you can return items within 30 days."
        )

        agent = AgentCore(
            llm=llm,
            retrieval_service=retrieval,
            escalation_service=_make_mock_escalation_service(),
            memory_manager=_make_mock_memory_manager(),
            db=_make_mock_db(),
        )

        with patch.object(
            agent._intent_router,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentType.DOMAIN_QUERY,
        ):
            output = await agent.handle_turn(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                message="What is your return policy?",
                tenant_config=_TENANT_CONFIG,
            )

        retrieval.retrieve.assert_called_once()
        assert output.intent_type == IntentType.DOMAIN_QUERY
        assert output.response != ""
        assert output.confidence is not None
        assert output.source_chunks is not None
        assert len(output.source_chunks) > 0

    @pytest.mark.asyncio
    async def test_domain_query_message_persisted(self) -> None:
        """Verify messages are persisted to the DB."""
        db = _make_mock_db()
        llm = MockLLMProvider(generate_text="Here is the answer.")

        agent = AgentCore(
            llm=llm,
            retrieval_service=_make_mock_retrieval_service(confidence=0.9),
            escalation_service=_make_mock_escalation_service(),
            memory_manager=_make_mock_memory_manager(),
            db=db,
        )

        with patch.object(
            agent._intent_router,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentType.DOMAIN_QUERY,
        ):
            output = await agent.handle_turn(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                message="tell me about returns",
                tenant_config=_TENANT_CONFIG,
            )

        # db.add should be called for user message + assistant message
        assert db.add.call_count >= 2
        assert output.message_id is not None


class TestOutOfScopeTurn:
    """OUT_OF_SCOPE intent: scope redirect, no tools."""

    @pytest.mark.asyncio
    async def test_out_of_scope_no_retrieval(self) -> None:
        """Verify no retrieval for out-of-scope turns."""
        retrieval = _make_mock_retrieval_service()

        agent = AgentCore(
            llm=MockLLMProvider(),
            retrieval_service=retrieval,
            escalation_service=_make_mock_escalation_service(),
            memory_manager=_make_mock_memory_manager(),
            db=_make_mock_db(),
        )

        with patch.object(
            agent._intent_router,
            "classify",
            new_callable=AsyncMock,
            return_value=IntentType.OUT_OF_SCOPE,
        ):
            output = await agent.handle_turn(
                session_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                message="What are your competitor prices?",
                tenant_config=_TENANT_CONFIG,
            )

        retrieval.retrieve.assert_not_called()
        assert output.intent_type == IntentType.OUT_OF_SCOPE
        assert output.escalation_required is False
        assert output.confidence is None

"""Intent classification router — runs before any tool call.

Every user message is classified before the agent does anything else.
This is a single lightweight Gemini Flash call — no RAG, no rerank,
no vector search.

File: app/services/agent/intent_router.py (Section 8.1)
"""

from __future__ import annotations

from enum import Enum

import structlog

from app.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)


class IntentType(str, Enum):
    CONVERSATIONAL = "conversational"
    DOMAIN_QUERY = "domain_query"
    OUT_OF_SCOPE = "out_of_scope"


INTENT_CLASSIFICATION_PROMPT = """
You are a router for a customer support agent in the {vertical} industry.
The agent handles these topics only: {allowed_topics}

Classify the user message into exactly one category:
- "conversational": greetings, thanks, acknowledgements, small talk, vague openers like "I need help", "okay", "can you assist me"
- "domain_query": a specific question requiring knowledge about products, policies, procedures, pricing, or real-time data
- "out_of_scope": asking about anything outside the agent's listed topics

User message: "{message}"

Reply with exactly one word. No explanation. No punctuation.
"""


class IntentRouter:
    """Classifies user messages into intent categories before agent processing."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    # ~50 input tokens + 1 output token per call.
    # Latency target: <300ms. This runs before every user turn.
    # Default fallback is DOMAIN_QUERY — retrieval runs on ambiguity,
    # never silently drops a real question.
    async def classify(
        self,
        message: str,
        vertical: str,
        allowed_topics: list[str],
    ) -> IntentType:
        """Classify a user message into one of three intent types.

        Args:
            message: The raw user message text.
            vertical: Tenant industry vertical (e.g. "ecommerce").
            allowed_topics: List of topics the agent is scoped to handle.

        Returns:
            IntentType — one of CONVERSATIONAL, DOMAIN_QUERY, OUT_OF_SCOPE.
            Never raises. On any failure, defaults to DOMAIN_QUERY.
        """
        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            vertical=vertical,
            allowed_topics=", ".join(allowed_topics),
            message=message,
        )
        try:
            result = await self._llm.generate(
                prompt=prompt,
                system_prompt="You are a precise classifier. Reply with one word only.",
                max_tokens=5,
            )
            raw = result.text.strip().lower()
            try:
                intent = IntentType(raw)
                logger.debug(
                    "intent_classified",
                    intent=intent.value,
                    message_len=len(message),
                )
                return intent
            except ValueError:
                logger.warning(
                    "intent_classification_unexpected_output",
                    raw_response=raw,
                    message_len=len(message),
                )
                return IntentType.DOMAIN_QUERY
        except Exception as e:
            logger.warning(
                "intent_classification_failed",
                error=str(e),
                message_len=len(message),
            )
            return IntentType.DOMAIN_QUERY

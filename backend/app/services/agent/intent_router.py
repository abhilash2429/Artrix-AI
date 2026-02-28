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

    @staticmethod
    def _parse_intent_label(raw: str) -> IntentType | None:
        """Parse classifier output into an IntentType.

        Accepts exact matches and common prefix truncations that Gemini
        produces due to low max_tokens. This is not heuristic intent
        inference — the LLM already decided, we are just parsing its
        output robustly.
        """
        cleaned = raw.strip().lower().strip("`\"'.,:;!?()[]{}")
        # Exact match
        if cleaned in {t.value for t in IntentType}:
            return IntentType(cleaned)
        # Gemini frequently truncates to prefix — match unambiguous prefixes
        for intent_type in IntentType:
            if intent_type.value.startswith(cleaned) and len(cleaned) >= 4:
                return intent_type
        return None

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
                system_prompt=(
                    "You are a precise classifier. "
                    "Reply with exactly one label: "
                    "conversational, domain_query, or out_of_scope."
                ),
                max_tokens=20,
            )
            raw = result.text
            intent = self._parse_intent_label(raw)
            if intent is None:
                logger.warning(
                    "intent_classification_unexpected_output",
                    raw_response=raw.strip().lower(),
                    message_len=len(message),
                )
                retry = await self._llm.generate(
                    prompt=(
                        "Return exactly one label for this user message:\n"
                        f"\"{message}\"\n\n"
                        "Allowed labels:\n"
                        "- conversational\n"
                        "- domain_query\n"
                        "- out_of_scope\n\n"
                        "Return only the label."
                    ),
                    system_prompt="Return exactly one allowed label only.",
                    max_tokens=10,
                )
                retry_raw = retry.text
                intent = self._parse_intent_label(retry_raw)
            if intent is None:
                logger.warning(
                    "intent_classification_retry_failed",
                    message_len=len(message),
                )
                # Both attempts failed to produce a valid label.
                # Default to CONVERSATIONAL — this avoids triggering
                # retrieval + escalation on simple greetings when the
                # classifier returns empty/blocked responses.
                return IntentType.CONVERSATIONAL
            logger.debug(
                "intent_classified",
                intent=intent.value,
                message_len=len(message),
            )
            return intent
        except Exception as e:
            logger.warning(
                "intent_classification_failed",
                error=str(e),
                message_len=len(message),
            )
            # LLM completely failed (timeout, blocked, network error).
            # Default to CONVERSATIONAL to avoid unnecessary retrieval
            # and escalation on simple inputs.
            return IntentType.CONVERSATIONAL

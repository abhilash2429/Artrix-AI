"""LangChain agent core — the main decision engine.

Follows the turn flow from Section 8.2 of agents.md:
  CONVERSATIONAL → direct response (no tools)
  DOMAIN_QUERY   → RAG pipeline → confidence check → answer or escalate
  OUT_OF_SCOPE   → scope redirect (no tools)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
import structlog
import tiktoken
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.services.agent.escalation import EscalationService
from app.services.agent.intent_router import IntentRouter, IntentType
from app.services.agent.memory import ConversationMemoryManager
from app.services.agent import tools as agent_tools
from app.services.llm.base import LLMProvider
from app.services.rag.retrieval import RetrievalService

logger = structlog.get_logger(__name__)

_ENCODER = tiktoken.get_encoding("cl100k_base")


@dataclass
class AgentTurnOutput:
    """Output from a single agent turn."""

    response: str
    intent_type: IntentType
    confidence: float | None = None
    source_chunks: list[dict[str, Any]] | None = None
    escalation_required: bool = False
    escalation_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    message_id: UUID | None = None


# Section 8.4 system prompt template
_SYSTEM_PROMPT_TEMPLATE = """You are {persona_name}, a customer support agent for {company_name}.

Your role: {persona_description}

Rules you must follow without exception:
1. Answer only from the context provided by the knowledge_retrieval tool. Never invent information.
2. If the retrieved context does not contain enough information to answer confidently, call escalate_to_human immediately. Do not guess.
3. If the user asks about: {blocked_topics}, politely decline and offer to help with something else.
4. Keep responses concise: 2–4 sentences for simple questions, structured lists for multi-part answers.
5. Never mention that you are an AI unless directly asked.
6. If you are unsure, say so and escalate. A wrong answer is worse than an escalation.
7. Always cite which part of the knowledge base your answer comes from (document name + section).

Current date: {current_date}
Tenant vertical: {vertical}"""


class AgentCore:
    """Main agent orchestrator. Dispatches based on intent classification."""

    def __init__(
        self,
        llm: LLMProvider,
        retrieval_service: RetrievalService,
        escalation_service: EscalationService,
        memory_manager: ConversationMemoryManager,
        db: AsyncSession,
    ) -> None:
        self._llm = llm
        self._retrieval_service = retrieval_service
        self._escalation_service = escalation_service
        self._memory_manager = memory_manager
        self._db = db
        self._intent_router = IntentRouter(llm)
        self._tools = self._build_tools()

    def _build_tools(self) -> dict[str, Any]:
        """Build tool closures capturing service references (Section 8.3).

        Tools are only invoked for DOMAIN_QUERY intents.
        """
        retrieval_svc = self._retrieval_service
        escalation_svc = self._escalation_service

        async def knowledge_retrieval(
            query: str, tenant_id: UUID, tenant_config: dict[str, Any],
        ) -> Any:
            """Tool 1: knowledge_retrieval — runs hybrid search + rerank."""
            logger.info("tool_call", tool="knowledge_retrieval", query_len=len(query))
            return await retrieval_svc.retrieve(
                query=query, tenant_id=tenant_id, tenant_config=tenant_config,
            )

        async def escalate_to_human(
            session_id: UUID, tenant_id: UUID, reason: str,
            last_user_message: str, webhook_url: str | None,
            external_user_id: str | None,
        ) -> str:
            """Tool 2: escalate_to_human — triggers escalation flow."""
            logger.info("tool_call", tool="escalate_to_human", reason=reason)
            await escalation_svc.escalate(
                session_id=session_id, tenant_id=tenant_id, reason=reason,
                last_user_message=last_user_message, webhook_url=webhook_url,
                external_user_id=external_user_id,
            )
            return agent_tools.format_escalation_output(reason)

        async def structured_data_lookup(
            lookup_type: str, identifier: str, data_webhook_url: str | None,
        ) -> str:
            """Tool 3: structured_data_lookup — live data from enterprise webhook."""
            logger.info("tool_call", tool="structured_data_lookup", lookup_type=lookup_type)
            return await agent_tools.structured_data_lookup(
                lookup_type=lookup_type, identifier=identifier,
                data_webhook_url=data_webhook_url,
            )

        return {
            "knowledge_retrieval": knowledge_retrieval,
            "escalate_to_human": escalate_to_human,
            "structured_data_lookup": structured_data_lookup,
        }

    @staticmethod
    def _build_system_prompt(tenant_config: dict[str, Any]) -> str:
        """Build the system prompt from tenant configuration (Section 8.4)."""
        return _SYSTEM_PROMPT_TEMPLATE.format(
            persona_name=tenant_config.get("persona_name", "Assistant"),
            company_name=tenant_config.get(
                "company_name",
                tenant_config.get("persona_name", "the company"),
            ),
            persona_description=tenant_config.get(
                "persona_description", "A helpful customer support agent."
            ),
            blocked_topics=", ".join(
                tenant_config.get("blocked_topics", [])
            )
            or "none",
            current_date=datetime.utcnow().strftime("%Y-%m-%d"),
            vertical=tenant_config.get("vertical", "general"),
        )

    @staticmethod
    def _count_tokens(text: str) -> int:
        """Count tokens using tiktoken cl100k_base encoding."""
        return len(_ENCODER.encode(text))

    async def _persist_messages(
        self,
        session_id: UUID,
        tenant_id: UUID,
        user_message: str,
        assistant_response: str,
        intent_type: str,
        source_chunks: list[dict[str, Any]] | None,
        confidence_score: float | None,
        escalation_flag: bool,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> UUID:
        """Persist user message and assistant response to Postgres."""
        user_msg = Message(
            session_id=session_id,
            tenant_id=tenant_id,
            role="user",
            content=user_message,
            intent_type=intent_type,
        )
        self._db.add(user_msg)

        assistant_msg = Message(
            session_id=session_id,
            tenant_id=tenant_id,
            role="assistant",
            content=assistant_response,
            intent_type=intent_type,
            source_chunks=source_chunks,
            confidence_score=confidence_score,
            escalation_flag=escalation_flag,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        self._db.add(assistant_msg)
        await self._db.flush()
        return assistant_msg.id

    async def handle_turn(
        self,
        session_id: UUID,
        tenant_id: UUID,
        message: str,
        tenant_config: dict[str, Any],
    ) -> AgentTurnOutput:
        """Process a single user message through the full agent turn flow.

        Uses a single LLM call for classify+respond (conversational/oos)
        to cut latency from 2 round-trips to 1 for non-RAG paths.
        """
        start = time.monotonic()

        vertical = tenant_config.get("vertical", "general")
        allowed_topics = tenant_config.get("allowed_topics", [])
        persona_name = tenant_config.get("persona_name", "Assistant")

        # ── Single combined classify+respond call ──────────────────
        memory = await self._memory_manager.load(session_id)
        chat_history = self._format_chat_history(memory)
        system_prompt = self._build_system_prompt(tenant_config)

        combined_prompt = (
            f"You are a router AND responder for a {vertical} support agent.\n"
            f"Allowed topics: {', '.join(allowed_topics)}\n\n"
            f"Chat history:\n{chat_history}\n"
            f"User message: \"{message}\"\n\n"
            "Step 1 — classify this message as exactly ONE of:\n"
            "  conversational | domain_query | out_of_scope\n\n"
            "Step 2 — if conversational or out_of_scope, write a helpful reply "
            f"as {persona_name}.\n"
            "If domain_query, write ONLY \"needs_retrieval\".\n\n"
            "Format your response EXACTLY like this:\n"
            "INTENT: <label>\n"
            "RESPONSE: <your reply or needs_retrieval>"
        )

        intent = IntentType.CONVERSATIONAL
        combined_response: str | None = None

        try:
            result = await self._llm.generate(
                prompt=combined_prompt,
                system_prompt=system_prompt,
                max_tokens=300,
                temperature=0.4,
            )
            raw = result.text.strip()
            intent, combined_response = self._parse_combined_response(raw)
            logger.debug(
                "combined_classify_ok",
                intent=intent.value,
                has_response=combined_response is not None,
                message_len=len(message),
            )
        except Exception as e:
            logger.warning("combined_classify_failed", error=str(e))
            # Fallback: treat as conversational with static greeting
            intent = IntentType.CONVERSATIONAL
            combined_response = None

        # ── Branch on intent ──────────────────────────────────────
        if intent == IntentType.DOMAIN_QUERY:
            output = await self._handle_domain_query(
                session_id, tenant_id, message, tenant_config
            )
        elif intent == IntentType.OUT_OF_SCOPE:
            response_text = combined_response or (
                "That's outside what I can help with. "
                f"I can assist with: {', '.join(allowed_topics)}."
            )
            memory.chat_memory.add_user_message(message)
            memory.chat_memory.add_ai_message(response_text)
            await self._memory_manager.save(session_id, memory)
            output = AgentTurnOutput(
                response=response_text,
                intent_type=IntentType.OUT_OF_SCOPE,
                input_tokens=self._count_tokens(message),
                output_tokens=self._count_tokens(response_text),
            )
        else:
            # CONVERSATIONAL — response already generated in combined call
            response_text = combined_response or (
                f"Hi there! I'm {persona_name}. How can I help you today?"
            )
            memory.chat_memory.add_user_message(message)
            memory.chat_memory.add_ai_message(response_text)
            await self._memory_manager.save(session_id, memory)
            output = AgentTurnOutput(
                response=response_text,
                intent_type=IntentType.CONVERSATIONAL,
                input_tokens=self._count_tokens(message),
                output_tokens=self._count_tokens(response_text),
            )

        # Persist messages to Postgres
        msg_id = await self._persist_messages(
            session_id=session_id,
            tenant_id=tenant_id,
            user_message=message,
            assistant_response=output.response,
            intent_type=output.intent_type.value,
            source_chunks=output.source_chunks,
            confidence_score=output.confidence,
            escalation_flag=output.escalation_required,
            input_tokens=output.input_tokens,
            output_tokens=output.output_tokens,
            latency_ms=0,
        )
        output.message_id = msg_id

        # Latency covers full handle_turn including persistence
        output.latency_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "agent_turn_complete",
            session_id=str(session_id),
            tenant_id=str(tenant_id),
            intent=output.intent_type.value,
            confidence=output.confidence,
            escalation=output.escalation_required,
            latency_ms=output.latency_ms,
            input_tokens=output.input_tokens,
            output_tokens=output.output_tokens,
        )

        return output

    @staticmethod
    def _parse_combined_response(raw: str) -> tuple[IntentType, str | None]:
        """Parse the combined classify+respond LLM output.

        Expected format:
            INTENT: <label>
            RESPONSE: <text or needs_retrieval>

        Returns (intent, response_text_or_None).
        """
        intent = IntentType.CONVERSATIONAL
        response: str | None = None

        lines = raw.split("\n", 1)
        first_line = lines[0].strip().lower()

        # Parse intent from first line
        if "intent:" in first_line:
            label = first_line.split("intent:", 1)[1].strip().strip("`\"'.,")
            for t in IntentType:
                if t.value.startswith(label) and len(label) >= 4:
                    intent = t
                    break
                if label == t.value:
                    intent = t
                    break
        elif any(t.value in first_line for t in IntentType):
            for t in IntentType:
                if t.value in first_line:
                    intent = t
                    break

        # Parse response from second part
        if len(lines) > 1:
            resp_part = lines[1].strip()
            if resp_part.lower().startswith("response:"):
                resp_part = resp_part[9:].strip()
            if resp_part and resp_part.lower() != "needs_retrieval":
                response = resp_part

        return intent, response

    # ── Branch A: CONVERSATIONAL ────────────────────────────────────

    async def _handle_conversational(
        self,
        session_id: UUID,
        tenant_id: UUID,
        message: str,
        tenant_config: dict[str, Any],
    ) -> AgentTurnOutput:
        """Handle CONVERSATIONAL intent — direct LLM response, no tools."""
        memory = await self._memory_manager.load(session_id)
        system_prompt = self._build_system_prompt(tenant_config)

        chat_history = self._format_chat_history(memory)
        prompt = f"{chat_history}User: {message}\nAssistant:"

        persona_name = tenant_config.get("persona_name", "Assistant")
        try:
            result = await self._llm.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=500,
                temperature=0.5,
            )
            response_text = result.text.strip()
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
        except Exception:
            response_text = ""
            input_tokens = 0
            output_tokens = 0

        # If LLM returned empty (blocked by safety filter), use a
        # static greeting so the user isn't left with a 500 error.
        if not response_text:
            response_text = (
                f"Hi there! I'm {persona_name}. How can I help you today?"
            )

        memory.chat_memory.add_user_message(message)
        memory.chat_memory.add_ai_message(response_text)
        await self._memory_manager.save(session_id, memory)

        return AgentTurnOutput(
            response=response_text,
            intent_type=IntentType.CONVERSATIONAL,
            confidence=None,
            source_chunks=None,
            escalation_required=False,
            escalation_reason=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # ── Branch B: DOMAIN_QUERY──────────────────────────────────────

    async def _handle_domain_query(
        self,
        session_id: UUID,
        tenant_id: UUID,
        message: str,
        tenant_config: dict[str, Any],
    ) -> AgentTurnOutput:
        """Handle DOMAIN_QUERY intent — full RAG pipeline."""
        memory = await self._memory_manager.load(session_id)
        system_prompt = self._build_system_prompt(tenant_config)

        turn_count = len(
            [m for m in memory.chat_memory.messages if isinstance(m, HumanMessage)]
        )

        retrieval_config = {
            "escalation_threshold": tenant_config.get(
                "escalation_threshold", 0.55
            ),
            "max_turns_before_escalation": tenant_config.get(
                "max_turns_before_escalation", 10
            ),
            "turn_count": turn_count,
        }
        retrieval_output = await self._tools["knowledge_retrieval"](
            query=message,
            tenant_id=tenant_id,
            tenant_config=retrieval_config,
        )

        # If retrieval returned zero results (empty knowledge base),
        # fall back to conversational response instead of escalating.
        # The spec says escalation is for knowledge GAPS, not empty KBs.
        if not retrieval_output.results:
            logger.info(
                "domain_query_empty_kb_fallback",
                session_id=str(session_id),
                message_len=len(message),
            )
            return await self._handle_conversational(
                session_id, tenant_id, message, tenant_config
            )

        # Check escalation
        if retrieval_output.should_escalate:
            webhook_url = tenant_config.get("escalation_webhook_url")
            external_user_id = tenant_config.get("external_user_id")

            await self._tools["escalate_to_human"](
                session_id=session_id,
                tenant_id=tenant_id,
                reason=retrieval_output.escalation_reason
                or "low_retrieval_confidence",
                last_user_message=message,
                webhook_url=webhook_url,
                external_user_id=external_user_id,
            )

            escalation_response = (
                "I don't have enough information to answer that confidently. "
                "Let me connect you with a human agent who can help."
            )
            return AgentTurnOutput(
                response=escalation_response,
                intent_type=IntentType.DOMAIN_QUERY,
                confidence=retrieval_output.confidence,
                source_chunks=self._format_source_chunks(
                    retrieval_output.results
                ),
                escalation_required=True,
                escalation_reason=retrieval_output.escalation_reason,
                input_tokens=self._count_tokens(message),
                output_tokens=self._count_tokens(escalation_response),
            )

        # Build context from retrieval results
        context_parts: list[str] = []
        for r in retrieval_output.results:
            source = (
                f"[{r.payload.get('filename', 'unknown')} — "
                f"{r.payload.get('section_heading', 'unknown')}]"
            )
            context_parts.append(f"{source}\n{r.text}")
        context_text = "\n\n---\n\n".join(context_parts)

        chat_history = self._format_chat_history(memory)
        prompt = (
            f"Context from knowledge base:\n{context_text}\n\n"
            f"Chat History:\n{chat_history}"
            f"User: {message}\n"
            f"Assistant:"
        )

        result = await self._llm.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=1000,
            temperature=0.3,
        )

        memory.chat_memory.add_user_message(message)
        memory.chat_memory.add_ai_message(result.text)
        await self._memory_manager.save(session_id, memory)

        return AgentTurnOutput(
            response=result.text,
            intent_type=IntentType.DOMAIN_QUERY,
            confidence=retrieval_output.confidence,
            source_chunks=self._format_source_chunks(
                retrieval_output.results
            ),
            escalation_required=False,
            escalation_reason=None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    # ── Branch C: OUT_OF_SCOPE──────────────────────────────────────

    async def _handle_out_of_scope(
        self,
        session_id: UUID,
        tenant_id: UUID,
        message: str,
        tenant_config: dict[str, Any],
    ) -> AgentTurnOutput:
        """Handle OUT_OF_SCOPE intent — scope redirect, no tools, no escalation."""
        allowed_topics = tenant_config.get("allowed_topics", [])
        persona_name = tenant_config.get("persona_name", "Assistant")

        system_prompt = (
            f"You are {persona_name}. "
            f"The user is asking about something outside your scope. "
            f"Politely decline and redirect to: {', '.join(allowed_topics)}"
        )

        result = await self._llm.generate(
            prompt=f"User: {message}\nAssistant:",
            system_prompt=system_prompt,
            max_tokens=200,
            temperature=0.3,
        )

        return AgentTurnOutput(
            response=result.text,
            intent_type=IntentType.OUT_OF_SCOPE,
            confidence=None,
            source_chunks=None,
            escalation_required=False,
            escalation_reason=None,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

    # ── Helpers──────────────────────────────────────────────────────

    @staticmethod
    def _format_chat_history(memory: Any) -> str:
        """Format conversation memory into a chat history string."""
        lines: list[str] = []
        for msg in memory.chat_memory.messages:
            if isinstance(msg, HumanMessage):
                lines.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                lines.append(f"Assistant: {msg.content}")
        return "\n".join(lines) + "\n" if lines else ""

    @staticmethod
    def _format_source_chunks(
        results: list[Any],
    ) -> list[dict[str, Any]]:
        """Format retrieval results into source chunk dicts for the response."""
        return [
            {
                "chunk_id": r.chunk_id,
                "document": r.payload.get("filename", "unknown"),
                "section": r.payload.get("section_heading", "unknown"),
            }
            for r in results
        ]

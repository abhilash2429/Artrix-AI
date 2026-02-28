"""Chat message endpoints."""

from __future__ import annotations

import json
from typing import AsyncGenerator
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_agent_core,
    get_billing_service,
    get_current_tenant,
    get_db,
    get_language_middleware,
)
from app.core.exceptions import InvalidSessionError, SessionInactiveError
from app.models.session import Session
from app.models.tenant import Tenant
from app.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    SourceChunk,
)
from app.services.agent.core import AgentCore
from app.services.billing import BillingService
from app.services.language.middleware import LanguageMiddleware

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _build_tenant_config(tenant: Tenant, session: Session) -> dict:
    """Build tenant_config dict from tenant model for AgentCore."""
    config = dict(tenant.config) if tenant.config else {}
    config.setdefault("vertical", tenant.vertical)
    config.setdefault("persona_name", "Assistant")
    config.setdefault("persona_description", "A helpful customer support agent.")
    config.setdefault("allowed_topics", [])
    config.setdefault("blocked_topics", [])
    config.setdefault("escalation_threshold", 0.55)
    config.setdefault("auto_resolve_threshold", 0.80)
    config.setdefault("max_turns_before_escalation", 10)
    config["external_user_id"] = session.external_user_id
    return config


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    body: ChatMessageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    agent: AgentCore = Depends(get_agent_core),
    billing: BillingService = Depends(get_billing_service),
    lang: LanguageMiddleware = Depends(get_language_middleware),
) -> ChatMessageResponse | StreamingResponse:
    """Process a chat message through the agent pipeline.

    Processing order:
    1. Verify session belongs to tenant and is active
    2. Language middleware: translate to English
    3. AgentCore.handle_turn()
    4. Language middleware: translate from English
    5. BillingService.record_message()
    6. If escalation: BillingService.close_session()
    7. Return response
    """
    # 1. Verify session
    result = await db.execute(
        select(Session).where(
            Session.id == body.session_id,
            Session.tenant_id == tenant.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise InvalidSessionError()
    if session.status != "active":
        raise SessionInactiveError()

    tenant_config = _build_tenant_config(tenant, session)

    # Handle streaming
    if body.stream:
        return StreamingResponse(
            _stream_response(
                message=body.message,
                session_id=body.session_id,
                tenant=tenant,
                session_obj=session,
                tenant_config=tenant_config,
                agent=agent,
                billing=billing,
                lang=lang,
            ),
            media_type="text/event-stream",
        )

    # 2. Language middleware: translate to English
    detected_lang = await lang.detect_language(body.message)
    translated_msg = await lang.translate_to_english(
        body.message, detected_lang
    )

    # 3. AgentCore.handle_turn()
    output = await agent.handle_turn(
        session_id=body.session_id,
        tenant_id=tenant.id,
        message=translated_msg,
        tenant_config=tenant_config,
    )

    # 4. Language middleware: translate from English
    translated_response = await lang.translate_from_english(
        output.response, detected_lang
    )

    # 5. BillingService.record_message()
    await billing.record_message(
        session_id=body.session_id,
        tenant_id=tenant.id,
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
    )

    # 6. If escalation: close session billing
    if output.escalation_required:
        await billing.close_session(
            session_id=body.session_id,
            tenant_id=tenant.id,
            event_type="escalated",
        )

    # 7. Return response
    sources = None
    if output.source_chunks:
        sources = [
            SourceChunk(
                chunk_id=s["chunk_id"],
                document=s["document"],
                section=s["section"],
            )
            for s in output.source_chunks
        ]

    return ChatMessageResponse(
        message_id=output.message_id,
        response=translated_response,
        confidence=output.confidence,
        sources=sources or [],
        escalation_required=output.escalation_required,
        escalation_reason=output.escalation_reason,
        latency_ms=output.latency_ms,
        intent_type=output.intent_type.value,
    )


async def _stream_response(
    message: str,
    session_id: UUID,
    tenant: Tenant,
    session_obj: Session,
    tenant_config: dict,
    agent: AgentCore,
    billing: BillingService,
    lang: LanguageMiddleware,
) -> AsyncGenerator[str, None]:
    """Generate SSE events with true token-by-token streaming from Gemini.

    Flow:
    1. Combined classify+respond call (single LLM call)
    2. If conversational/oos: stream the response directly
    3. If domain_query: run retrieval, then stream the RAG response
    4. Final metadata event with confidence, sources, etc.
    """
    import time
    start = time.monotonic()

    detected_lang = await lang.detect_language(message)
    translated_msg = await lang.translate_to_english(message, detected_lang)

    vertical = tenant_config.get("vertical", "general")
    allowed_topics = tenant_config.get("allowed_topics", [])
    persona_name = tenant_config.get("persona_name", "Assistant")

    # Load memory for chat history context
    memory = await agent._memory_manager.load(session_id)
    chat_history = agent._format_chat_history(memory)
    system_prompt = agent._build_system_prompt(tenant_config)

    # Combined classify+respond (same prompt as handle_turn)
    combined_prompt = (
        f"You are a router AND responder for a {vertical} support agent.\n"
        f"Allowed topics: {', '.join(allowed_topics)}\n\n"
        f"Chat history:\n{chat_history}\n"
        f"User message: \"{translated_msg}\"\n\n"
        "Step 1 — classify this message as exactly ONE of:\n"
        "  conversational | domain_query | out_of_scope\n\n"
        "Step 2 — if conversational or out_of_scope, write a helpful reply "
        f"as {persona_name}.\n"
        "If domain_query, write ONLY \"needs_retrieval\".\n\n"
        "Format your response EXACTLY like this:\n"
        "INTENT: <label>\n"
        "RESPONSE: <your reply or needs_retrieval>"
    )

    from app.services.agent.intent_router import IntentType

    full_text = ""
    intent = IntentType.CONVERSATIONAL
    streaming_started = False

    try:
        # Stream the combined classify+respond call
        async for chunk in agent._llm.stream(
            prompt=combined_prompt,
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.4,
        ):
            full_text += chunk

            # Parse intent from first line as soon as we have it
            if not streaming_started and "\n" in full_text:
                first_line = full_text.split("\n", 1)[0].strip().lower()
                if "domain_query" in first_line:
                    intent = IntentType.DOMAIN_QUERY
                    break  # Stop streaming — need retrieval
                elif "out_of_scope" in first_line:
                    intent = IntentType.OUT_OF_SCOPE

                # Start streaming the response part
                streaming_started = True
                response_part = full_text.split("\n", 1)[1]
                if response_part.lower().startswith("response:"):
                    response_part = response_part[9:].lstrip()
                if response_part:
                    event = json.dumps({"delta": response_part, "done": False})
                    yield f"data: {event}\n\n"
            elif streaming_started:
                # Stream subsequent chunks directly
                event = json.dumps({"delta": chunk, "done": False})
                yield f"data: {event}\n\n"

    except Exception as e:
        logger.warning("stream_classify_failed", error=str(e))
        intent = IntentType.CONVERSATIONAL

    response_text = ""
    sources = None
    confidence = None

    if intent == IntentType.DOMAIN_QUERY:
        # Run retrieval then stream the RAG response
        output = await agent.handle_turn(
            session_id=session_id,
            tenant_id=tenant.id,
            message=translated_msg,
            tenant_config=tenant_config,
        )
        # Stream the completed response word by word
        words = output.response.split(" ")
        for i, word in enumerate(words):
            delta = word if i == 0 else f" {word}"
            event = json.dumps({"delta": delta, "done": False})
            yield f"data: {event}\n\n"
        response_text = output.response
        confidence = output.confidence
        if output.source_chunks:
            sources = [
                {
                    "chunk_id": s["chunk_id"],
                    "document": s["document"],
                    "section": s["section"],
                }
                for s in output.source_chunks
            ]
    else:
        # Extract response text from the streamed output
        if "\n" in full_text:
            resp_part = full_text.split("\n", 1)[1]
            if resp_part.lower().startswith("response:"):
                resp_part = resp_part[9:].lstrip()
            response_text = resp_part.strip()
        if not response_text:
            response_text = f"Hi there! I'm {persona_name}. How can I help you today?"
            event = json.dumps({"delta": response_text, "done": False})
            yield f"data: {event}\n\n"

        # Save to memory
        memory.chat_memory.add_user_message(translated_msg)
        memory.chat_memory.add_ai_message(response_text)
        await agent._memory_manager.save(session_id, memory)

        # Persist to DB
        await agent._persist_messages(
            session_id=session_id,
            tenant_id=tenant.id,
            user_message=translated_msg,
            assistant_response=response_text,
            intent_type=intent.value,
            source_chunks=None,
            confidence_score=None,
            escalation_flag=False,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )

    await billing.record_message(
        session_id=session_id,
        tenant_id=tenant.id,
        input_tokens=0,
        output_tokens=0,
    )

    latency_ms = int((time.monotonic() - start) * 1000)

    # Final metadata event
    metadata = {
        "confidence": confidence,
        "sources": sources,
        "escalation_required": False,
        "escalation_reason": None,
        "latency_ms": latency_ms,
        "intent_type": intent.value,
    }
    final_event = json.dumps({"done": True, "metadata": metadata})
    yield f"data: {final_event}\n\n"

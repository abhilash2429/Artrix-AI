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
    """Generate SSE events for streaming chat responses.

    For CONVERSATIONAL turns: streams LLM output directly.
    For DOMAIN_QUERY: runs retrieval first, then streams generation.
    """
    detected_lang = await lang.detect_language(message)
    translated_msg = await lang.translate_to_english(message, detected_lang)

    # Run the full turn (non-streaming for simplicity in Phase 1)
    output = await agent.handle_turn(
        session_id=session_id,
        tenant_id=tenant.id,
        message=translated_msg,
        tenant_config=tenant_config,
    )

    translated_response = await lang.translate_from_english(
        output.response, detected_lang
    )

    await billing.record_message(
        session_id=session_id,
        tenant_id=tenant.id,
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
    )

    if output.escalation_required:
        await billing.close_session(
            session_id=session_id,
            tenant_id=tenant.id,
            event_type="escalated",
        )

    # Stream the response word by word for progressive display
    words = translated_response.split(" ")
    for i, word in enumerate(words):
        delta = word if i == 0 else f" {word}"
        event = json.dumps({"delta": delta, "done": False})
        yield f"data: {event}\n\n"

    # Final metadata event
    sources = None
    if output.source_chunks:
        sources = [
            {
                "chunk_id": s["chunk_id"],
                "document": s["document"],
                "section": s["section"],
            }
            for s in output.source_chunks
        ]

    metadata = {
        "confidence": output.confidence,
        "sources": sources,
        "escalation_required": output.escalation_required,
        "escalation_reason": output.escalation_reason,
        "latency_ms": output.latency_ms,
    }
    final_event = json.dumps({"done": True, "metadata": metadata})
    yield f"data: {final_event}\n\n"

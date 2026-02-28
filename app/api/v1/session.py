"""Session management endpoints."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_billing_service,
    get_current_tenant,
    get_db,
    get_memory_manager,
)
from app.core.exceptions import InvalidSessionError
from app.models.message import Message
from app.models.session import Session
from app.models.tenant import Tenant
from app.schemas.session import (
    SessionEndResponse,
    SessionStartRequest,
    SessionStartResponse,
    SessionTranscriptResponse,
    TranscriptMessage,
)
from app.services.agent.memory import ConversationMemoryManager
from app.services.billing import BillingService

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/start", response_model=SessionStartResponse)
async def start_session(
    body: SessionStartRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    billing: BillingService = Depends(get_billing_service),
) -> SessionStartResponse:
    """Start a new conversation session."""
    session = Session(
        tenant_id=tenant.id,
        external_user_id=body.external_user_id,
    )
    db.add(session)
    await db.flush()

    # Initialize billing counters in Redis with 0 tokens
    await billing.record_message(
        session_id=session.id,
        tenant_id=tenant.id,
        input_tokens=0,
        output_tokens=0,
    )

    return SessionStartResponse(
        session_id=session.id,
        created_at=session.started_at,
    )


@router.post("/{session_id}/end", response_model=SessionEndResponse)
async def end_session(
    session_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    billing: BillingService = Depends(get_billing_service),
    memory_manager: ConversationMemoryManager = Depends(get_memory_manager),
) -> SessionEndResponse:
    """End a conversation session."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.tenant_id == tenant.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise InvalidSessionError()

    session.status = "resolved"
    session.ended_at = datetime.now(timezone.utc)
    await db.flush()

    await billing.close_session(
        session_id=session_id,
        tenant_id=tenant.id,
        event_type="resolved",
    )

    await memory_manager.clear(session_id)

    return SessionEndResponse(
        session_id=session_id,
        status="resolved",
    )


@router.get(
    "/{session_id}/transcript", response_model=SessionTranscriptResponse
)
async def get_transcript(
    session_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> SessionTranscriptResponse:
    """Get the full transcript of a conversation session."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.tenant_id == tenant.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise InvalidSessionError()

    msg_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = msg_result.scalars().all()

    return SessionTranscriptResponse(
        session_id=session_id,
        messages=[
            TranscriptMessage(
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                intent_type=m.intent_type,
                confidence_score=m.confidence_score,
                escalation_flag=m.escalation_flag,
            )
            for m in messages
        ],
    )

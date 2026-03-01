"""Shared FastAPI dependencies — auth, database sessions, service injection.

The FallbackLLMProvider (Cerebras primary + Gemini fallback) is created once during
the FastAPI lifespan and stored on app.state. All downstream code retrieves
it via Depends() — never by direct import. embed() lives on LLMProvider.
"""

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidAPIKeyError, TenantInactiveError
from app.core.security import hash_api_key
from app.db.postgres import get_async_session
from app.db.qdrant import QdrantService, get_qdrant as _get_qdrant
from app.db.redis import RedisClient, get_redis as _get_redis
from app.models.tenant import Tenant
from app.services.agent.core import AgentCore
from app.services.agent.escalation import EscalationService
from app.services.agent.memory import ConversationMemoryManager
from app.services.billing import BillingService
from app.services.language.middleware import LanguageMiddleware
from app.services.llm.base import LLMProvider
from app.services.rag.ingestion import IngestionService
from app.services.rag.retrieval import RetrievalService


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

async def get_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncSession:
    """Yield an async database session."""
    return session


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

async def get_redis() -> RedisClient:
    """Return the singleton RedisClient wrapper."""
    return await _get_redis()


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------

async def get_qdrant_service() -> QdrantService:
    """Return the singleton QdrantService wrapper."""
    return await _get_qdrant()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

async def get_current_tenant(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Authenticate and return the current tenant from the API key header."""
    if not x_api_key:
        raise InvalidAPIKeyError()

    key_hash = hash_api_key(x_api_key)
    result = await db.execute(
        select(Tenant).where(Tenant.api_key_hash == key_hash)
    )
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise InvalidAPIKeyError()

    if not tenant.is_active:
        raise TenantInactiveError()

    return tenant


# ---------------------------------------------------------------------------
# Service singleton — retrieved from app.state (set during lifespan)
# ---------------------------------------------------------------------------

def get_llm_provider(request: Request) -> LLMProvider:
    """Return the singleton LLM provider from app state.

    The LLMProvider exposes generate(), stream(), and embed().
    There is no separate EmbeddingProvider — embed() lives here.
    """
    return request.app.state.llm_provider


# ---------------------------------------------------------------------------
# Service constructors — wired via Depends()
# ---------------------------------------------------------------------------

async def get_memory_manager(
    redis: RedisClient = Depends(get_redis),
) -> ConversationMemoryManager:
    """Return a ConversationMemoryManager instance."""
    return ConversationMemoryManager(redis=redis, window_size=10)


async def get_escalation_service(
    db: AsyncSession = Depends(get_db),
    memory_manager: ConversationMemoryManager = Depends(get_memory_manager),
) -> EscalationService:
    """Return an EscalationService instance."""
    return EscalationService(db=db, memory_manager=memory_manager)


async def get_retrieval_service(
    llm: LLMProvider = Depends(get_llm_provider),
    qdrant: QdrantService = Depends(get_qdrant_service),
    redis: RedisClient = Depends(get_redis),
) -> RetrievalService:
    """Return a RetrievalService instance."""
    return RetrievalService(llm=llm, qdrant=qdrant, redis=redis)


async def get_agent_core(
    llm: LLMProvider = Depends(get_llm_provider),
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
    escalation_service: EscalationService = Depends(get_escalation_service),
    memory_manager: ConversationMemoryManager = Depends(get_memory_manager),
    db: AsyncSession = Depends(get_db),
) -> AgentCore:
    """Return an AgentCore instance fully wired with all dependencies."""
    return AgentCore(
        llm=llm,
        retrieval_service=retrieval_service,
        escalation_service=escalation_service,
        memory_manager=memory_manager,
        db=db,
    )


async def get_billing_service(
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
) -> BillingService:
    """Return a BillingService instance."""
    return BillingService(db=db, redis=redis)


def get_language_middleware() -> LanguageMiddleware:
    """Return a LanguageMiddleware instance (Phase 1: passthrough)."""
    return LanguageMiddleware()


async def get_ingestion_service(
    llm: LLMProvider = Depends(get_llm_provider),
    qdrant: QdrantService = Depends(get_qdrant_service),
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis),
) -> IngestionService:
    """Return an IngestionService instance."""
    return IngestionService(
        llm=llm, qdrant=qdrant, db_session=db, redis=redis
    )

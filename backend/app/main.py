"""FastAPI application entrypoint.

All routes prefixed /v1. CORS configured per tenant domain_whitelist.
Auto-generated OpenAPI docs at /docs.

A FallbackLLMProvider wrapping CerebrasProvider (primary) and GeminiProvider (fallback)
is created once during the lifespan and stored on app.state for injection via Depends().
Idle session cleanup runs every 5 minutes via APScheduler.
"""

from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
import warnings

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.chat import router as chat_router
from app.api.v1.config import router as config_router
from app.api.v1.health import router as health_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.session import router as session_router
from app.core.config import settings
from app.core.exceptions import ArtrixError
from app.db.postgres import async_session_factory, close_postgres
from app.db.qdrant import close_qdrant
from app.db.redis import RedisClient, close_redis, get_redis
from app.services.billing import BillingService
from app.services.llm.cerebras import CerebrasProvider
from app.services.llm.fallback import FallbackLLMProvider
from app.services.llm.gemini import GeminiProvider

warnings.filterwarnings(
    "ignore",
    message="urllib3 .* doesn't match a supported version!",
    category=Warning,
)


def _configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_configure_logging()

logger = structlog.get_logger(__name__)


async def _idle_session_cleanup() -> None:
    """Auto-close idle sessions. Called by APScheduler every 5 minutes."""
    try:
        redis = await get_redis()
        async with async_session_factory() as db:
            billing = BillingService(db=db, redis=redis)
            await billing.auto_close_idle_sessions()
            await db.commit()
    except Exception as e:
        logger.error("idle_session_cleanup_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle.

    Creates the singleton LLM provider and attaches it to app.state.
    Retrieved in request handlers via Depends() in app/api/deps.py.
    embed() lives on LLMProvider — no separate embedding provider.
    Also starts the APScheduler for idle session cleanup.
    """
    # --- Startup ---
    logger.info("app_startup", env=settings.app_env)

    cerebras = CerebrasProvider(
        api_key=settings.cerebras_api_key,
        model="llama3.1-8b",
    )
    gemini = GeminiProvider(
        api_key=settings.gemini_api_key,
        model="gemini-2.0-flash",
    )
    app.state.llm_provider = FallbackLLMProvider(
        primary=cerebras,
        secondary=gemini,
    )

    # Start APScheduler for idle session cleanup every 5 minutes
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _idle_session_cleanup,
        "interval",
        minutes=5,
        id="idle_session_cleanup",
    )
    scheduler.start()
    app.state.scheduler = scheduler

    logger.info("app_providers_ready")
    yield

    # --- Shutdown ---
    logger.info("app_shutdown")

    scheduler.shutdown(wait=False)

    await close_redis()
    await close_qdrant()
    await close_postgres()


app = FastAPI(
    title="Artrix AI — Chat Agent API",
    description="Multi-tenant AI chat agent backend for Indian enterprises.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — permissive for development, tenant-scoped in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ArtrixError)
async def artrix_error_handler(request: Request, exc: ArtrixError) -> JSONResponse:
    """Structured error response for all Artrix exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


# Mount all v1 routers
app.include_router(health_router, prefix="/v1")
app.include_router(session_router, prefix="/v1")
app.include_router(chat_router, prefix="/v1")
app.include_router(knowledge_router, prefix="/v1")
app.include_router(config_router, prefix="/v1")

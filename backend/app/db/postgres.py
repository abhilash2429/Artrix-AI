"""Async SQLAlchemy engine and session factory for PostgreSQL.

All database operations use the SQLAlchemy 2.0 async session pattern.
Connection errors are caught and re-raised as DatabaseConnectionError
so the API layer receives a typed, structured error.
"""

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.exceptions import DatabaseConnectionError

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


engine: AsyncEngine = create_async_engine(
    settings.postgres_url,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    Commits on success, rolls back on exception, always closes.
    SQLAlchemy driver errors are caught and re-raised as DatabaseConnectionError.
    """
    try:
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error("postgres_session_error", error=str(e))
                raise DatabaseConnectionError(f"Database operation failed: {e}") from e
            except Exception:
                await session.rollback()
                raise
    except DatabaseConnectionError:
        raise
    except SQLAlchemyError as e:
        logger.error("postgres_connection_error", error=str(e))
        raise DatabaseConnectionError(f"Database connection failed: {e}") from e


async def close_postgres() -> None:
    """Gracefully dispose of the async engine connection pool."""
    logger.info("postgres_shutdown")
    await engine.dispose()

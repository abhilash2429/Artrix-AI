"""Knowledge ingestion endpoints."""

import os
import tempfile
from uuid import UUID

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_tenant,
    get_db,
    get_qdrant_service,
    get_redis,
)
from app.core.exceptions import DocumentNotFoundError, InvalidFileTypeError
from app.db.qdrant import QdrantService
from app.db.redis import RedisClient
from app.models.knowledge import KnowledgeDocument
from app.models.tenant import Tenant
from app.schemas.knowledge import (
    DocumentDeleteResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentStatusResponse,
    IngestResponse,
)
from app.services.llm.base import LLMProvider
from app.api.deps import get_llm_provider

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_ALLOWED_EXTENSIONS = {"pdf", "docx", "html", "txt", "csv"}


def _get_extension(filename: str) -> str:
    """Extract file extension (lowercase, no dot)."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()


async def _run_ingestion_background(
    document_id: str,
    tenant_id: str,
    filepath: str,
    filename: str,
    document_version: int,
    llm: LLMProvider,
    qdrant: QdrantService,
    redis: RedisClient,
) -> None:
    """Run ingestion in background with its own DB session."""
    from app.db.postgres import async_session_factory
    from app.services.rag.ingestion import IngestionService

    try:
        async with async_session_factory() as db:
            svc = IngestionService(
                llm=llm, qdrant=qdrant, db_session=db, redis=redis
            )
            await svc.run(
                document_id=document_id,
                tenant_id=tenant_id,
                filepath=filepath,
                filename=filename,
                document_version=document_version,
            )
            await db.commit()
    except Exception as e:
        logger.error(
            "background_ingestion_failed",
            document_id=document_id,
            error=str(e),
        )
    finally:
        # Clean up temp file
        try:
            os.unlink(filepath)
        except OSError:
            pass


@router.post("/ingest", status_code=202, response_model=IngestResponse)
async def ingest_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(get_llm_provider),
    qdrant: QdrantService = Depends(get_qdrant_service),
    redis: RedisClient = Depends(get_redis),
) -> IngestResponse:
    """Ingest a document into the knowledge base."""
    if not file.filename:
        raise InvalidFileTypeError("No filename provided")

    ext = _get_extension(file.filename)
    if ext not in _ALLOWED_EXTENSIONS:
        raise InvalidFileTypeError(
            f"File type '.{ext}' not supported. Allowed: {_ALLOWED_EXTENSIONS}"
        )

    # Save file to temp path
    suffix = f".{ext}"
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=suffix
    ) as tmp:
        content = await file.read()
        tmp.write(content)
        filepath = tmp.name

    # Create knowledge_documents row
    doc = KnowledgeDocument(
        tenant_id=tenant.id,
        filename=file.filename,
        file_type=ext,
        status="processing",
    )
    db.add(doc)
    await db.flush()

    # Launch ingestion as background task
    background_tasks.add_task(
        _run_ingestion_background,
        document_id=str(doc.id),
        tenant_id=str(tenant.id),
        filepath=filepath,
        filename=file.filename,
        document_version=doc.version,
        llm=llm,
        qdrant=qdrant,
        redis=redis,
    )

    return IngestResponse(
        document_id=doc.id,
        status="processing",
        message=f"Ingestion started. Poll /v1/knowledge/{doc.id}/status",
    )


@router.get(
    "/{document_id}/status", response_model=DocumentStatusResponse
)
async def get_document_status(
    document_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Get the ingestion status of a document."""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == tenant.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError()

    return DocumentStatusResponse(
        document_id=doc.id,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
    )


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List all active documents for the tenant."""
    result = await db.execute(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.tenant_id == tenant.id,
            KnowledgeDocument.is_active.is_(True),
        )
        .order_by(KnowledgeDocument.ingested_at.desc())
    )
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=d.id,
                filename=d.filename,
                version=d.version,
                status=d.status,
                ingested_at=d.ingested_at,
                chunk_count=d.chunk_count,
            )
            for d in docs
        ]
    )


@router.delete(
    "/{document_id}", response_model=DocumentDeleteResponse
)
async def delete_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
    qdrant: QdrantService = Depends(get_qdrant_service),
    redis: RedisClient = Depends(get_redis),
) -> DocumentDeleteResponse:
    """Soft-delete a document and schedule Qdrant vector cleanup."""
    result = await db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == tenant.id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError()

    # Soft delete
    await db.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .values(is_active=False)
    )
    await db.flush()

    # Synchronous BM25 cache invalidation (before returning)
    from app.services.rag.retrieval import invalidate_bm25_cache
    await invalidate_bm25_cache(str(tenant.id), redis)

    # Background: delete Qdrant vectors only
    async def cleanup_vectors() -> None:
        try:
            await qdrant.delete_by_filter(
                tenant_id=str(tenant.id),
                filters={"document_id": str(document_id)},
            )
        except Exception as e:
            logger.error(
                "vector_cleanup_failed",
                document_id=str(document_id),
                error=str(e),
            )

    background_tasks.add_task(cleanup_vectors)

    return DocumentDeleteResponse(deleted=True)

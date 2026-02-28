"""Standalone ingestion pipeline runner (CLI-invokable).

Usage:
    python -m ingestion.pipeline \\
        --tenant-id <uuid> \\
        --file-path path/to/document.pdf \\
        --document-type faq

Instantiates all services directly (not via FastAPI Depends — runs outside
the HTTP context). Executes the full ingestion pipeline synchronously via
``asyncio.run()``.

Exit codes:
    0 — success
    1 — failure (error printed to stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


async def run_ingestion(
    tenant_id: str,
    file_path: str,
    document_type: str,
) -> None:
    """Run the full ingestion pipeline for a single document.

    Creates the ``knowledge_documents`` record, instantiates all services
    directly, and delegates to ``IngestionService.run()``.
    """
    # Late imports so module-level code doesn't trigger config loading
    # when just importing the module (e.g., for testing)
    from app.core.config import settings
    from app.db.postgres import async_session_factory
    from app.db.qdrant import QdrantService, _client as qdrant_client
    from app.db.redis import RedisClient, _client as redis_client
    from app.models.knowledge import KnowledgeDocument
    from app.services.llm.gemini import GeminiProvider
    from app.services.rag.ingestion import IngestionService

    filepath = Path(file_path)
    filename = filepath.name
    file_type = filepath.suffix.lstrip(".").lower()

    # Instantiate services outside of FastAPI DI
    llm = GeminiProvider(api_key=settings.gemini_api_key, model="gemini-2.5-flash")
    qdrant = QdrantService(qdrant_client)
    redis = RedisClient(redis_client)

    async with async_session_factory() as session:
        # Create knowledge_documents record
        doc_id = uuid.uuid4()
        doc = KnowledgeDocument(
            id=doc_id,
            tenant_id=uuid.UUID(tenant_id),
            filename=filename,
            file_type=file_type,
            version=1,
            status="processing",
            ingested_at=datetime.now(timezone.utc),
        )
        session.add(doc)
        await session.commit()

        print(f"[ingestion] Created document record: {doc_id}")
        print(f"[ingestion] File: {file_path} ({file_type})")
        print(f"[ingestion] Document type: {document_type}")
        print(f"[ingestion] Tenant: {tenant_id}")
        print()

        service = IngestionService(llm=llm, qdrant=qdrant, db_session=session, redis=redis)

        print("[ingestion] Starting pipeline...")
        total_points = await service.run(
            document_id=str(doc_id),
            tenant_id=tenant_id,
            filepath=str(filepath),
            filename=filename,
            document_version=1,
        )

        # Refresh to display final status
        await session.refresh(doc)

        print()
        print(f"[ingestion] ✓ Pipeline complete")
        print(f"[ingestion]   Document ID:  {doc_id}")
        print(f"[ingestion]   Status:       {doc.status}")
        print(f"[ingestion]   Chunk count:  {doc.chunk_count}")
        print(f"[ingestion]   Qdrant points: {total_points}")


def main() -> None:
    """CLI entrypoint with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Artrix AI — Document Ingestion CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m ingestion.pipeline \\\n"
            "    --tenant-id 550e8400-e29b-41d4-a716-446655440000 \\\n"
            "    --file-path docs/return_policy.pdf \\\n"
            "    --document-type policy\n"
        ),
    )
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Tenant UUID",
    )
    parser.add_argument(
        "--file-path",
        required=True,
        help="Path to document file (pdf, docx, html, txt, csv)",
    )
    parser.add_argument(
        "--document-type",
        required=True,
        choices=["faq", "policy", "product_catalog", "sop"],
        help="Document classification type",
    )
    args = parser.parse_args()

    # Validate file exists
    if not Path(args.file_path).exists():
        print(f"[error] File not found: {args.file_path}", file=sys.stderr)
        sys.exit(1)

    # Validate tenant_id is a valid UUID
    try:
        uuid.UUID(args.tenant_id)
    except ValueError:
        print(
            f"[error] Invalid tenant UUID: {args.tenant_id}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        asyncio.run(run_ingestion(
            tenant_id=args.tenant_id,
            file_path=args.file_path,
            document_type=args.document_type,
        ))
        sys.exit(0)
    except Exception as e:
        print(f"[error] Pipeline failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

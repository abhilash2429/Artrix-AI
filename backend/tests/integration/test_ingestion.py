"""Integration tests for document ingestion pipeline.

Tests:
  - Ingest parsed elements → verify non-empty chunks
  - No chunk exceeds 550 tokens
  - Each chunk has a chunk_id
  - Qdrant upsert was called (mock QdrantService, assert call count > 0)
  - knowledge_documents.status = 'ready' after successful run
  - knowledge_documents.status = 'failed' when Qdrant raises exception
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.ingestion import (
    Chunk,
    ChunkMetadata,
    ParsedElement,
    chunk_elements,
    embed_and_store,
    generate_chunk_metadata,
    _count_tokens,
)
from tests.conftest import MockLLMProvider, MockQdrantService, MockRedisClient


class TestIngestionParsedElements:
    """Test the chunking phase of the ingestion pipeline."""

    def test_parsed_elements_produce_chunks(self) -> None:
        """Parsing real-ish elements should produce non-empty chunk list."""
        elements = [
            ParsedElement(
                text="Frequently Asked Questions",
                element_type="Title",
                section_heading="FAQ",
            ),
            ParsedElement(
                text="How do I return an item? You can return any item within 30 days.",
                element_type="NarrativeText",
                section_heading="FAQ",
            ),
            ParsedElement(
                text="What is the refund timeline? Refunds are processed within 5-7 business days.",
                element_type="NarrativeText",
                section_heading="FAQ",
            ),
        ]
        chunks = chunk_elements(elements)
        assert len(chunks) > 0

    def test_each_chunk_has_id(self) -> None:
        """Every chunk must have a non-empty chunk_id."""
        elements = [
            ParsedElement(
                text="Section title",
                element_type="Title",
                section_heading="Title",
            ),
            ParsedElement(
                text="Some content about returns and refunds policy.",
                element_type="NarrativeText",
                section_heading="Title",
            ),
        ]
        chunks = chunk_elements(elements)
        for chunk in chunks:
            assert chunk.chunk_id
            # Verify it's a valid UUID
            uuid.UUID(chunk.chunk_id)

    def test_no_chunk_exceeds_550_tokens(self) -> None:
        """No chunk should exceed 550 tokens (500 + 10% tolerance)."""
        elements = [
            ParsedElement(
                text=" ".join(f"word{i}" for i in range(600)),
                element_type="NarrativeText",
                section_heading="LargeDoc",
            ),
        ]
        chunks = chunk_elements(elements)
        for chunk in chunks:
            assert _count_tokens(chunk.text) <= 550


class TestIngestionMetadata:
    """Test the metadata generation phase."""

    @pytest.mark.asyncio
    async def test_metadata_generation_populates_chunks(self) -> None:
        """generate_chunk_metadata should populate summary and questions."""
        llm = MockLLMProvider(
            generate_text='{"summary": "Test summary", "questions": ["Q1?", "Q2?", "Q3?"]}'
        )
        chunks = [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                text="Return policy content here",
                token_count=10,
                element_type="NarrativeText",
                section_heading="Returns",
            )
        ]
        result = await generate_chunk_metadata(chunks, llm)
        assert len(result) == 1
        assert result[0].metadata.summary == "Test summary"
        assert len(result[0].metadata.hypothetical_questions) == 3


class TestIngestionEmbedAndStore:
    """Test the embed + Qdrant storage phase."""

    @pytest.mark.asyncio
    async def test_qdrant_upsert_called(self) -> None:
        """embed_and_store should call Qdrant upsert at least once."""
        llm = MockLLMProvider()
        qdrant = MockQdrantService()

        chunks = [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                text="Test chunk text",
                token_count=5,
                element_type="NarrativeText",
                section_heading="Test",
                metadata=ChunkMetadata(
                    summary="A test summary",
                    hypothetical_questions=["Q1?", "Q2?", "Q3?"],
                ),
            )
        ]

        total_points = await embed_and_store(
            chunks=chunks,
            tenant_id="test-tenant-id",
            document_id="test-doc-id",
            filename="test.pdf",
            document_version=1,
            llm=llm,
            qdrant=qdrant,  # type: ignore[arg-type]
        )

        assert total_points > 0
        assert len(qdrant.upsert_calls) > 0
        assert qdrant.collections_created == ["test-tenant-id"]

    @pytest.mark.asyncio
    async def test_three_vectors_per_chunk(self) -> None:
        """Each chunk should produce 3 Qdrant points (raw, summary, hypothetical)."""
        llm = MockLLMProvider()
        qdrant = MockQdrantService()

        chunks = [
            Chunk(
                chunk_id=str(uuid.uuid4()),
                text="Test chunk text for embedding",
                token_count=6,
                element_type="NarrativeText",
                section_heading="Test",
                metadata=ChunkMetadata(
                    summary="A summary",
                    hypothetical_questions=["Q1?", "Q2?", "Q3?"],
                ),
            )
        ]

        total_points = await embed_and_store(
            chunks=chunks,
            tenant_id="tid",
            document_id="did",
            filename="file.pdf",
            document_version=1,
            llm=llm,
            qdrant=qdrant,  # type: ignore[arg-type]
        )

        # 3 vectors: raw + summary + hypothetical
        assert total_points == 3


class TestIngestionServiceStatusTransitions:
    """Test IngestionService.run() status transitions."""

    @pytest.mark.asyncio
    async def test_successful_run_marks_ready(self, fixture_pdf_path: str) -> None:
        """After successful ingestion, document status should be 'ready'."""
        from sqlalchemy import update as sa_update
        from app.services.rag.ingestion import IngestionService

        llm = MockLLMProvider(
            generate_text='{"summary": "Test", "questions": ["Q1?", "Q2?", "Q3?"]}'
        )
        qdrant = MockQdrantService()
        redis = MockRedisClient()

        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock())
        db.commit = AsyncMock()

        svc = IngestionService(
            llm=llm, qdrant=qdrant, db_session=db, redis=redis  # type: ignore[arg-type]
        )

        # Mock parse_document to avoid needing a real file parser
        with patch(
            "app.services.rag.ingestion.parse_document",
            return_value=[
                ParsedElement(
                    text="Test content",
                    element_type="NarrativeText",
                    section_heading="Test",
                )
            ],
        ):
            total = await svc.run(
                document_id=str(uuid.uuid4()),
                tenant_id=str(uuid.uuid4()),
                filepath=fixture_pdf_path,
                filename="test_document.pdf",
            )

        assert total > 0
        # Verify status transitions by inspecting db.execute calls
        execute_calls = db.execute.call_args_list
        # Should have at least: SET processing, SET ready
        assert len(execute_calls) >= 2
        assert db.commit.call_count >= 2

        # Verify final status update sets 'ready'
        # The last execute call before the final commit should be the status='ready' update
        found_ready = False
        for call in execute_calls:
            stmt = call[0][0]
            compiled = str(stmt)
            if "ready" in compiled:
                found_ready = True
        assert found_ready, "Expected a status='ready' update in db.execute calls"

    @pytest.mark.asyncio
    async def test_qdrant_failure_marks_failed(self, fixture_pdf_path: str) -> None:
        """When Qdrant raises, document status should be 'failed'."""
        from app.services.rag.ingestion import IngestionService

        llm = MockLLMProvider(
            generate_text='{"summary": "Test", "questions": ["Q1?", "Q2?", "Q3?"]}'
        )

        # Qdrant that raises on upsert
        qdrant = MockQdrantService()

        async def _raise_on_upsert(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Qdrant connection failed")

        qdrant.upsert_vectors = _raise_on_upsert  # type: ignore[assignment]

        redis = MockRedisClient()
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock())
        db.commit = AsyncMock()

        svc = IngestionService(
            llm=llm, qdrant=qdrant, db_session=db, redis=redis  # type: ignore[arg-type]
        )

        with patch(
            "app.services.rag.ingestion.parse_document",
            return_value=[
                ParsedElement(
                    text="Test content that will fail",
                    element_type="NarrativeText",
                    section_heading="Test",
                )
            ],
        ):
            with pytest.raises(Exception):
                await svc.run(
                    document_id=str(uuid.uuid4()),
                    tenant_id=str(uuid.uuid4()),
                    filepath=fixture_pdf_path,
                    filename="test_document.pdf",
                )

        # Verify status was set to 'failed'
        execute_calls = db.execute.call_args_list
        found_failed = False
        for call in execute_calls:
            stmt = call[0][0]
            compiled = str(stmt)
            if "failed" in compiled:
                found_failed = True
        assert found_failed, "Expected a status='failed' update in db.execute calls"

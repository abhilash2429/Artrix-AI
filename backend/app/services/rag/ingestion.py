"""Document parsing, chunking, metadata generation, and vector storage.

Full implementation of Section 6 from agents.md.

Pipeline: parse_document → chunk_elements → generate_chunk_metadata → embed_and_store
Orchestrated by IngestionService.run() which also manages Postgres status transitions.

Public API:
    - parse_document(filepath) → list[ParsedElement]   (sync — run via asyncio.to_thread)
    - chunk_elements(elements) → list[Chunk]            (sync — pure computation)
    - generate_chunk_metadata(chunks, llm) → list[Chunk] (async — LLM calls)
    - embed_and_store(chunks, ..., llm, qdrant) → int   (async — embed + Qdrant upsert)
    - IngestionService.run(...)                          (async — full orchestrator)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import structlog
import tiktoken
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IngestionError
from app.db.qdrant import QdrantService
from app.db.redis import RedisClient
from app.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENCODER = tiktoken.get_encoding("cl100k_base")

_TARGET_CHUNK_TOKENS = 450  # midpoint of 400–500
_MIN_CHUNK_TOKENS = 100     # below this we merge with next block
_MAX_CHUNK_TOKENS = 500
_OVERLAP_TOKENS = 50

_METADATA_CONCURRENCY = 5   # max parallel Gemini metadata calls

_METADATA_PROMPT = (
    "Given this document chunk, generate exactly 3 questions that a customer "
    "support user might ask that this chunk directly answers. Also generate a "
    "one-sentence summary of what the chunk contains.\n"
    'Return only a JSON object: {{"summary": "...", "questions": ["...", "...", "..."]}}.\n'
    "No preamble. No markdown.\n\n"
    "Chunk:\n{chunk_text}"
)

_EMBED_BATCH_SIZE = 100  # Qdrant upsert batch size


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ParsedElement:
    """A typed element extracted from a document by unstructured."""

    text: str
    element_type: str          # "Title", "NarrativeText", "Table", "ListItem", etc.
    section_heading: str | None = None
    page_number: int | None = None


@dataclass
class ChunkMetadata:
    """LLM-generated metadata for a chunk (populated in step 3c)."""

    summary: str = ""
    hypothetical_questions: list[str] = field(default_factory=list)


@dataclass
class Chunk:
    """A document chunk ready for embedding and storage."""

    chunk_id: str              # UUID string
    text: str
    token_count: int
    element_type: str
    section_heading: str | None = None
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)


# ===================================================================
# 3a — Document Parsing
# ===================================================================

class _TableHTMLParser(HTMLParser):
    """Minimal HTML parser that extracts table rows and cells."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] = []
        self._current_cell: str = ""
        self._in_cell: bool = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._in_cell = False
            self._current_row.append(self._current_cell.strip())
        elif tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell += data


def _table_to_markdown(element: Any) -> str:
    """Convert an unstructured Table element to markdown grid format.

    Uses ``metadata.text_as_html`` when available; falls back to raw text
    with a ``Table:`` prefix to preserve some structure.
    """
    html: str | None = getattr(
        getattr(element, "metadata", None), "text_as_html", None
    )

    if html:
        parser = _TableHTMLParser()
        try:
            parser.feed(html)
            if parser.rows:
                return _rows_to_markdown(parser.rows)
        except Exception:
            pass  # fall through to raw text

    return f"Table:\n{element.text}"


def _rows_to_markdown(rows: list[list[str]]) -> str:
    """Render a list of rows (lists of cell strings) as a markdown table."""
    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    for row in rows:
        while len(row) < max_cols:
            row.append("")

    col_widths = [
        max(len(rows[r][c]) for r in range(len(rows)))
        for c in range(max_cols)
    ]
    col_widths = [max(w, 3) for w in col_widths]

    lines: list[str] = []

    # Header
    header = "| " + " | ".join(
        rows[0][c].ljust(col_widths[c]) for c in range(max_cols)
    ) + " |"
    lines.append(header)

    # Separator
    separator = "| " + " | ".join(
        "-" * col_widths[c] for c in range(max_cols)
    ) + " |"
    lines.append(separator)

    # Data rows
    for row in rows[1:]:
        line = "| " + " | ".join(
            row[c].ljust(col_widths[c]) for c in range(max_cols)
        ) + " |"
        lines.append(line)

    return "\n".join(lines)


def _count_tokens(text: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return len(_ENCODER.encode(text))


def _decode_tokens(token_ids: list[int]) -> str:
    """Decode token IDs back to text."""
    return _ENCODER.decode(token_ids)


def parse_document(filepath: str) -> list[ParsedElement]:
    """Parse a document into typed elements using the unstructured library.

    Synchronous — call via ``asyncio.to_thread`` from async context.

    Uses ``partition(strategy="hi_res")`` for structure-aware extraction.
    Tracks section headings: updated on every Title element, attached to all
    subsequent elements until the next Title.
    Tables are converted to markdown grid format via ``_table_to_markdown``.
    """
    from unstructured.partition.auto import partition

    raw_elements = partition(filename=filepath, strategy="hi_res")

    parsed: list[ParsedElement] = []
    current_heading: str | None = None

    for el in raw_elements:
        el_type: str = type(el).__name__
        page_num: int | None = getattr(
            getattr(el, "metadata", None), "page_number", None
        )

        if el_type == "Title":
            current_heading = el.text.strip()
            text = current_heading
        elif el_type == "Table":
            text = _table_to_markdown(el)
        else:
            text = el.text.strip() if el.text else ""

        if not text:
            continue

        parsed.append(ParsedElement(
            text=text,
            element_type=el_type,
            section_heading=current_heading,
            page_number=page_num,
        ))

    logger.info("document_parsed", filepath=filepath, element_count=len(parsed))
    return parsed


# ===================================================================
# 3b — Structure-Aware Chunking
# ===================================================================

@dataclass
class _LogicalBlock:
    """Intermediate grouping of elements before final chunking."""

    text: str
    token_count: int
    element_type: str
    section_heading: str | None
    is_atomic: bool  # True → never split (tables, title+para, list groups)


def _create_logical_blocks(elements: list[ParsedElement]) -> list[_LogicalBlock]:
    """Group parsed elements into logical blocks respecting never-split rules.

    - Table → always one atomic block (never split regardless of token count)
    - Consecutive ListItems → merged into one atomic block
    - Title + immediately following non-Title → merged into one atomic block
    - Everything else → individual non-atomic block
    """
    blocks: list[_LogicalBlock] = []
    i = 0

    while i < len(elements):
        el = elements[i]

        if el.element_type == "Table":
            tokens = _count_tokens(el.text)
            blocks.append(_LogicalBlock(
                text=el.text,
                token_count=tokens,
                element_type="Table",
                section_heading=el.section_heading,
                is_atomic=True,
            ))
            i += 1

        elif el.element_type == "Title":
            combined_text = el.text
            merged_type = "Title"
            heading = el.section_heading

            # Merge Title with the immediately following non-Title element
            if (
                i + 1 < len(elements)
                and elements[i + 1].element_type != "Title"
            ):
                combined_text = el.text + "\n\n" + elements[i + 1].text
                merged_type = elements[i + 1].element_type
                i += 1  # consume the next element

            tokens = _count_tokens(combined_text)
            blocks.append(_LogicalBlock(
                text=combined_text,
                token_count=tokens,
                element_type=merged_type,
                section_heading=heading,
                is_atomic=True,
            ))
            i += 1

        elif el.element_type == "ListItem":
            list_texts: list[str] = [el.text]
            heading = el.section_heading
            i += 1
            while i < len(elements) and elements[i].element_type == "ListItem":
                list_texts.append(elements[i].text)
                i += 1

            combined = "\n".join(f"• {t}" for t in list_texts)
            tokens = _count_tokens(combined)
            blocks.append(_LogicalBlock(
                text=combined,
                token_count=tokens,
                element_type="ListItem",
                section_heading=heading,
                is_atomic=True,
            ))

        else:
            tokens = _count_tokens(el.text)
            blocks.append(_LogicalBlock(
                text=el.text,
                token_count=tokens,
                element_type=el.element_type,
                section_heading=el.section_heading,
                is_atomic=False,
            ))
            i += 1

    return blocks


def _split_text_with_overlap(
    text: str,
    max_tokens: int = _MAX_CHUNK_TOKENS,
    overlap_tokens: int = _OVERLAP_TOKENS,
) -> list[str]:
    """Split long text into token-bounded chunks with overlap.

    Returns a list of text strings. Consecutive chunks share
    ``overlap_tokens`` tokens at their boundary.
    """
    token_ids = _ENCODER.encode(text)

    if len(token_ids) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))
        chunk_ids = token_ids[start:end]
        chunks.append(_decode_tokens(chunk_ids))

        if end >= len(token_ids):
            break

        start = end - overlap_tokens

    return chunks


def chunk_elements(elements: list[ParsedElement]) -> list[Chunk]:
    """Chunk parsed elements into retrieval-sized pieces.

    Target: 400–500 tokens per chunk (tiktoken cl100k_base).
    Overlap: 50 tokens between consecutive chunks from the same section.
    Hard rules: never split mid-table, mid-list, or title from first paragraph.
    """
    blocks = _create_logical_blocks(elements)
    chunks: list[Chunk] = []

    # Buffer for merging small non-atomic blocks within the same section
    buffer_text = ""
    buffer_tokens = 0
    buffer_type = "NarrativeText"
    buffer_heading: str | None = None

    def _flush_buffer() -> None:
        nonlocal buffer_text, buffer_tokens, buffer_type, buffer_heading
        if not buffer_text.strip():
            buffer_text = ""
            buffer_tokens = 0
            return

        if buffer_tokens > _MAX_CHUNK_TOKENS:
            for sub in _split_text_with_overlap(buffer_text):
                tc = _count_tokens(sub)
                chunks.append(Chunk(
                    chunk_id=str(uuid.uuid4()),
                    text=sub.strip(),
                    token_count=tc,
                    element_type=buffer_type,
                    section_heading=buffer_heading,
                ))
        else:
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid4()),
                text=buffer_text.strip(),
                token_count=buffer_tokens,
                element_type=buffer_type,
                section_heading=buffer_heading,
            ))

        buffer_text = ""
        buffer_tokens = 0

    for block in blocks:
        # Section change → flush buffer
        if block.section_heading != buffer_heading and buffer_text:
            _flush_buffer()
            buffer_heading = block.section_heading

        if buffer_heading is None:
            buffer_heading = block.section_heading

        if block.is_atomic:
            # Flush current buffer first
            _flush_buffer()

            if block.token_count > _MAX_CHUNK_TOKENS and block.element_type != "Table":
                # Split oversized non-table atomic blocks (e.g., huge list groups)
                for sub in _split_text_with_overlap(block.text):
                    tc = _count_tokens(sub)
                    chunks.append(Chunk(
                        chunk_id=str(uuid.uuid4()),
                        text=sub.strip(),
                        token_count=tc,
                        element_type=block.element_type,
                        section_heading=block.section_heading,
                    ))
            else:
                # Tables always one chunk regardless of size
                chunks.append(Chunk(
                    chunk_id=str(uuid.uuid4()),
                    text=block.text.strip(),
                    token_count=block.token_count,
                    element_type=block.element_type,
                    section_heading=block.section_heading,
                ))

            buffer_heading = block.section_heading

        else:
            # Non-atomic → try to merge into buffer
            if buffer_tokens + block.token_count > _MAX_CHUNK_TOKENS:
                _flush_buffer()
                buffer_heading = block.section_heading

            buffer_text = (
                buffer_text + "\n\n" + block.text if buffer_text else block.text
            )
            buffer_tokens = _count_tokens(buffer_text)
            buffer_type = block.element_type

    _flush_buffer()

    logger.info("elements_chunked", chunk_count=len(chunks))
    return chunks


# ===================================================================
# 3c — Metadata Generation (background — must not block ingestion)
# ===================================================================

def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        # Remove first line (```json or ```)
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


async def generate_chunk_metadata(
    chunks: list[Chunk],
    llm: LLMProvider,
) -> list[Chunk]:
    """Generate summary + hypothetical questions for each chunk via Gemini.

    Runs concurrently with a semaphore to avoid rate-limit issues.
    Metadata failures are logged but never raise — a failed metadata
    generation must not fail the ingestion.
    """
    semaphore = asyncio.Semaphore(_METADATA_CONCURRENCY)

    async def _generate_single(chunk: Chunk) -> None:
        async with semaphore:
            prompt = _METADATA_PROMPT.format(chunk_text=chunk.text)
            raw_text = ""
            try:
                response = await llm.generate(
                    prompt=prompt,
                    system_prompt=(
                        "You are a precise metadata generator. "
                        "Return only valid JSON."
                    ),
                    max_tokens=300,
                    temperature=0.2,
                )
                raw_text = response.text
                cleaned = _strip_markdown_fences(raw_text)
                data: dict[str, Any] = json.loads(cleaned)
                chunk.metadata = ChunkMetadata(
                    summary=data.get("summary", ""),
                    hypothetical_questions=data.get("questions", []),
                )
            except json.JSONDecodeError:
                logger.warning(
                    "metadata_json_parse_failed",
                    chunk_id=chunk.chunk_id,
                    raw_response=raw_text[:200],
                )
                chunk.metadata = ChunkMetadata()
            except Exception as e:
                logger.warning(
                    "metadata_generation_failed",
                    chunk_id=chunk.chunk_id,
                    error=str(e),
                )
                chunk.metadata = ChunkMetadata()

    tasks = [_generate_single(c) for c in chunks]
    await asyncio.gather(*tasks)

    success_count = sum(1 for c in chunks if c.metadata.summary)
    logger.info(
        "metadata_generated",
        total=len(chunks),
        success=success_count,
        failed=len(chunks) - success_count,
    )
    return chunks


# ===================================================================
# 3d / 3e — Embedding + Qdrant Storage
# ===================================================================

async def embed_and_store(
    chunks: list[Chunk],
    tenant_id: str,
    document_id: str,
    filename: str,
    document_version: int,
    llm: LLMProvider,
    qdrant: QdrantService,
) -> int:
    """Embed chunks (3 vectors each) and upsert to Qdrant.

    Vector 1: raw chunk text  (vector_type = "raw")
    Vector 2: LLM-generated summary  (vector_type = "summary", skip if empty)
    Vector 3: concatenated hypothetical questions  (vector_type = "hypothetical", skip if empty)

    All three are separate Qdrant points sharing the same ``chunk_id`` in payload.
    Returns the total number of Qdrant points upserted.
    """
    await qdrant.create_collection_if_not_exists(tenant_id)

    now_iso = datetime.now(timezone.utc).isoformat()
    points: list[dict[str, Any]] = []

    for chunk in chunks:
        base_payload: dict[str, Any] = {
            "chunk_id": chunk.chunk_id,
            "document_id": document_id,
            "tenant_id": tenant_id,
            "filename": filename,
            "document_version": document_version,
            "is_latest_version": True,
            "section_heading": chunk.section_heading,
            "element_type": chunk.element_type,
            "chunk_text": chunk.text,
            "char_count": len(chunk.text),
            "token_count": chunk.token_count,
            "summary": chunk.metadata.summary,
            "hypothetical_questions": chunk.metadata.hypothetical_questions,
            "ingested_at": now_iso,
        }

        # Vector 1 — raw text (mandatory)
        try:
            raw_vector = await llm.embed(chunk.text)
            points.append({
                "id": str(uuid.uuid4()),
                "vector": raw_vector,
                "payload": {**base_payload, "vector_type": "raw"},
            })
        except Exception as e:
            logger.error(
                "embed_raw_failed", chunk_id=chunk.chunk_id, error=str(e)
            )
            continue  # skip this chunk entirely if raw embedding fails

        # Vector 2 — summary (skip if empty)
        if chunk.metadata.summary:
            try:
                summary_vector = await llm.embed(chunk.metadata.summary)
                points.append({
                    "id": str(uuid.uuid4()),
                    "vector": summary_vector,
                    "payload": {**base_payload, "vector_type": "summary"},
                })
            except Exception as e:
                logger.warning(
                    "embed_summary_failed",
                    chunk_id=chunk.chunk_id,
                    error=str(e),
                )

        # Vector 3 — hypothetical questions (skip if empty)
        if chunk.metadata.hypothetical_questions:
            questions_text = " ".join(chunk.metadata.hypothetical_questions)
            try:
                questions_vector = await llm.embed(questions_text)
                points.append({
                    "id": str(uuid.uuid4()),
                    "vector": questions_vector,
                    "payload": {**base_payload, "vector_type": "hypothetical"},
                })
            except Exception as e:
                logger.warning(
                    "embed_hypothetical_failed",
                    chunk_id=chunk.chunk_id,
                    error=str(e),
                )

    # Batch upsert to Qdrant
    if points:
        for i in range(0, len(points), _EMBED_BATCH_SIZE):
            batch = points[i : i + _EMBED_BATCH_SIZE]
            await qdrant.upsert_vectors(tenant_id, batch)

    logger.info(
        "vectors_upserted",
        tenant_id=tenant_id,
        document_id=document_id,
        total_points=len(points),
        chunk_count=len(chunks),
    )
    return len(points)


# ===================================================================
# 3f — Orchestrator
# ===================================================================

class IngestionService:
    """Orchestrates the full document ingestion pipeline.

    Pipeline: parse → chunk → generate metadata → embed → store in Qdrant
    Updates ``knowledge_documents`` status in Postgres at each phase boundary:
      - ``processing`` at start
      - ``ready`` + chunk_count on success
      - ``failed`` + error_message on any unhandled exception
    """

    def __init__(
        self,
        llm: LLMProvider,
        qdrant: QdrantService,
        db_session: AsyncSession,
        redis: RedisClient | None = None,
    ) -> None:
        self._llm = llm
        self._qdrant = qdrant
        self._db = db_session
        self._redis = redis

    async def run(
        self,
        document_id: str,
        tenant_id: str,
        filepath: str,
        filename: str,
        document_version: int = 1,
    ) -> int:
        """Run the full ingestion pipeline for a single document.

        Args:
            document_id: UUID string of the knowledge_documents record.
            tenant_id: UUID string of the owning tenant.
            filepath: Absolute path to the document file on disk.
            filename: Original filename (stored in Qdrant payload metadata).
            document_version: Version number of this document.

        Returns:
            Total number of Qdrant points upserted.

        Raises:
            IngestionError: On any unhandled exception during the pipeline.
        """
        from app.models.knowledge import KnowledgeDocument

        doc_uuid = uuid.UUID(document_id)

        try:
            # ── Mark as processing ──────────────────────────────────
            await self._db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_uuid)
                .values(status="processing")
            )
            await self._db.commit()

            # ── Step 1: Parse ───────────────────────────────────────
            logger.info(
                "ingestion_parse_start",
                document_id=document_id,
                filepath=filepath,
            )
            elements = await asyncio.to_thread(parse_document, filepath)
            logger.info(
                "ingestion_parse_done",
                document_id=document_id,
                element_count=len(elements),
            )

            # ── Step 2: Chunk ───────────────────────────────────────
            logger.info("ingestion_chunk_start", document_id=document_id)
            chunks = chunk_elements(elements)
            logger.info(
                "ingestion_chunk_done",
                document_id=document_id,
                chunk_count=len(chunks),
            )

            # ── Step 3: Generate metadata ───────────────────────────
            logger.info("ingestion_metadata_start", document_id=document_id)
            chunks = await generate_chunk_metadata(chunks, self._llm)
            logger.info("ingestion_metadata_done", document_id=document_id)

            # ── Step 4: Embed and store ─────────────────────────────
            logger.info("ingestion_embed_start", document_id=document_id)
            total_points = await embed_and_store(
                chunks=chunks,
                tenant_id=tenant_id,
                document_id=document_id,
                filename=filename,
                document_version=document_version,
                llm=self._llm,
                qdrant=self._qdrant,
            )

            # ── Mark as ready ───────────────────────────────────────
            await self._db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_uuid)
                .values(status="ready", chunk_count=len(chunks))
            )
            await self._db.commit()

            # ── Invalidate BM25 cache ──────────────────────────────
            if self._redis is not None:
                from app.services.rag.retrieval import invalidate_bm25_cache
                await invalidate_bm25_cache(tenant_id, self._redis)

            logger.info(
                "ingestion_complete",
                document_id=document_id,
                chunk_count=len(chunks),
                total_points=total_points,
            )
            return total_points

        except Exception as e:
            logger.error(
                "ingestion_failed",
                document_id=document_id,
                error=str(e),
            )
            # Best-effort status update to 'failed'
            try:
                await self._db.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc_uuid)
                    .values(status="failed", error_message=str(e))
                )
                await self._db.commit()
            except Exception as db_err:
                logger.error(
                    "ingestion_status_update_failed", error=str(db_err)
                )

            raise IngestionError(f"Ingestion failed for {document_id}: {e}") from e

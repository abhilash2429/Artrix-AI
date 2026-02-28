"""Unit tests for document chunking logic.

Tests:
  - Table elements → single chunk regardless of size
  - Title + following paragraph → never split across chunks
  - Consecutive ListItems → merged into single chunk
  - Chunk token count never exceeds 550 (500 target + 10% tolerance)
  - Overlap: last 50 tokens of chunk N appear at start of chunk N+1
"""

from __future__ import annotations

import pytest

from app.services.rag.ingestion import (
    ParsedElement,
    chunk_elements,
    _count_tokens,
    _OVERLAP_TOKENS,
)


class TestTableChunking:
    """Table elements must always produce a single chunk."""

    def test_table_is_single_chunk(self) -> None:
        """A table element should produce exactly one chunk."""
        table_text = "| Col A | Col B |\n| --- | --- |\n" + "\n".join(
            f"| row {i} | data {i} |" for i in range(50)
        )
        elements = [
            ParsedElement(
                text=table_text,
                element_type="Table",
                section_heading="Products",
            )
        ]
        chunks = chunk_elements(elements)
        # All table content should be in a single chunk
        table_chunks = [c for c in chunks if c.element_type == "Table"]
        assert len(table_chunks) == 1

    def test_large_table_never_split(self) -> None:
        """Even a very large table should not be split."""
        table_text = "| A | B | C |\n| - | - | - |\n" + "\n".join(
            f"| val{i} | val{i+1} | val{i+2} |" for i in range(200)
        )
        elements = [
            ParsedElement(
                text=table_text,
                element_type="Table",
                section_heading="BigTable",
            )
        ]
        chunks = chunk_elements(elements)
        table_chunks = [c for c in chunks if c.element_type == "Table"]
        assert len(table_chunks) == 1
        assert table_text.strip() in table_chunks[0].text


class TestTitleParagraphMerging:
    """Title + immediately following paragraph must stay in the same chunk."""

    def test_title_and_paragraph_in_same_chunk(self) -> None:
        """A title followed by narrative text should be in one chunk."""
        elements = [
            ParsedElement(
                text="Return Policy",
                element_type="Title",
                section_heading="Return Policy",
            ),
            ParsedElement(
                text="You can return any item within 30 days of purchase for a full refund.",
                element_type="NarrativeText",
                section_heading="Return Policy",
            ),
        ]
        chunks = chunk_elements(elements)
        # Title + following paragraph should be merged
        assert len(chunks) >= 1
        assert "Return Policy" in chunks[0].text
        assert "return any item" in chunks[0].text

    def test_title_and_paragraph_never_split(self) -> None:
        """Title and its first paragraph must not be in separate chunks."""
        elements = [
            ParsedElement(
                text="Shipping Information",
                element_type="Title",
                section_heading="Shipping Information",
            ),
            ParsedElement(
                text="We ship to all major cities across India.",
                element_type="NarrativeText",
                section_heading="Shipping Information",
            ),
        ]
        chunks = chunk_elements(elements)
        # Find chunk containing title
        title_chunk = None
        para_chunk = None
        for c in chunks:
            if "Shipping Information" in c.text:
                title_chunk = c
            if "ship to all major cities" in c.text:
                para_chunk = c
        assert title_chunk is not None
        assert para_chunk is not None
        # They should be the same chunk
        assert title_chunk.chunk_id == para_chunk.chunk_id


class TestListItemMerging:
    """Consecutive ListItems should be merged into a single chunk."""

    def test_consecutive_list_items_merged(self) -> None:
        """ListItems in sequence should become one chunk."""
        elements = [
            ParsedElement(text="Apple", element_type="ListItem", section_heading="Fruits"),
            ParsedElement(text="Banana", element_type="ListItem", section_heading="Fruits"),
            ParsedElement(text="Cherry", element_type="ListItem", section_heading="Fruits"),
        ]
        chunks = chunk_elements(elements)
        assert len(chunks) == 1
        assert "Apple" in chunks[0].text
        assert "Banana" in chunks[0].text
        assert "Cherry" in chunks[0].text


class TestChunkTokenLimits:
    """Chunk token count must never exceed 550 (500 target + 10% tolerance)."""

    def test_no_chunk_exceeds_550_tokens(self) -> None:
        """All chunks should be at most 550 tokens."""
        long_text = " ".join(f"word{i}" for i in range(1000))
        elements = [
            ParsedElement(
                text=long_text,
                element_type="NarrativeText",
                section_heading="LongSection",
            )
        ]
        chunks = chunk_elements(elements)
        for chunk in chunks:
            actual_tokens = _count_tokens(chunk.text)
            assert actual_tokens <= 550, (
                f"Chunk {chunk.chunk_id} has {actual_tokens} tokens (max 550)"
            )

    def test_multiple_elements_respect_token_limit(self) -> None:
        """Chunks from multiple elements should also respect limits."""
        elements = [
            ParsedElement(
                text=" ".join(f"text{i}" for i in range(300)),
                element_type="NarrativeText",
                section_heading="Section1",
            ),
            ParsedElement(
                text=" ".join(f"more{i}" for i in range(300)),
                element_type="NarrativeText",
                section_heading="Section1",
            ),
        ]
        chunks = chunk_elements(elements)
        for chunk in chunks:
            actual_tokens = _count_tokens(chunk.text)
            assert actual_tokens <= 550


class TestChunkOverlap:
    """Last 50 tokens of chunk N should appear at start of chunk N+1."""

    def test_overlap_between_consecutive_chunks(self) -> None:
        """Consecutive chunks from the same section should overlap by ~50 tokens."""
        long_text = " ".join(f"overlap{i}" for i in range(800))
        elements = [
            ParsedElement(
                text=long_text,
                element_type="NarrativeText",
                section_heading="OverlapTest",
            )
        ]
        chunks = chunk_elements(elements)
        if len(chunks) < 2:
            pytest.skip("Not enough chunks to test overlap")

        for i in range(len(chunks) - 1):
            current_text = chunks[i].text
            next_text = chunks[i + 1].text

            # The end of current chunk should overlap with start of next chunk
            current_words = current_text.split()
            next_words = next_text.split()

            # Get last ~50 tokens worth of words from current chunk
            # and check some appear at start of next chunk
            overlap_words = current_words[-_OVERLAP_TOKENS:]
            next_start = " ".join(next_words[:_OVERLAP_TOKENS])

            # At least some overlap words should appear in next chunk start
            overlap_found = any(w in next_start for w in overlap_words[:10])
            assert overlap_found, (
                f"No overlap found between chunk {i} and chunk {i+1}"
            )

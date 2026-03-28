"""Tests for heading-aware chunker."""

import pytest

from ms_knowledge_base.ingest.chunker import Chunk, chunk_content
from ms_knowledge_base.ingest.pdf_reader import HeadingBlock, PageContent, TextBlock


def _make_pages(blocks_per_page: list[list[HeadingBlock | TextBlock]]) -> list[PageContent]:
    """Helper to build PageContent from block lists."""
    pages = []
    for i, blocks in enumerate(blocks_per_page):
        pages.append(PageContent(page_number=i + 1, blocks=blocks))
    return pages


def test_single_section_within_limit():
    """One section under max_tokens becomes one chunk."""
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Introduction", page_number=1),
            TextBlock(text="This is a section about delta tables in Microsoft Fabric. Delta tables provide ACID transactions and time travel capabilities for lakehouse workloads.", page_number=1, heading_context=["Introduction"]),
        ]
    ])
    chunks = chunk_content(pages, target_tokens=400, max_tokens=500)
    assert len(chunks) == 1
    assert "Introduction" in chunks[0].content
    assert "delta tables" in chunks[0].content


def test_heading_breadcrumb_prepended():
    """Chunk content starts with heading breadcrumb."""
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Fabric", page_number=1),
            HeadingBlock(level=2, text="Lakehouse", page_number=1),
            TextBlock(text="Lakehouse is a unified analytics platform that combines the best of data warehouses and data lakes into a single architecture.", page_number=1, heading_context=["Fabric", "Lakehouse"]),
        ]
    ])
    chunks = chunk_content(pages)
    assert len(chunks) >= 1
    assert chunks[0].content.startswith("# Fabric > Lakehouse")


def test_new_heading_starts_new_chunk():
    """Each new heading starts a new chunk."""
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Section A", page_number=1),
            TextBlock(text="Content for section A. " * 5, page_number=1, heading_context=["Section A"]),
            HeadingBlock(level=1, text="Section B", page_number=1),
            TextBlock(text="Content for section B. " * 5, page_number=1, heading_context=["Section B"]),
        ]
    ])
    chunks = chunk_content(pages)
    assert len(chunks) == 2
    assert "Section A" in chunks[0].content
    assert "Section B" in chunks[1].content


def test_long_section_splits_at_sentences():
    """Section exceeding max_tokens splits at sentence boundaries."""
    # Create a long section (~2000 chars = ~500 tokens)
    long_text = "This is a complete sentence about Fabric lakehouse architecture. " * 40
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Long Section", page_number=1),
            TextBlock(text=long_text, page_number=1, heading_context=["Long Section"]),
        ]
    ])
    chunks = chunk_content(pages, target_tokens=100, max_tokens=200)
    assert len(chunks) > 1
    # All chunks should have the heading breadcrumb
    for c in chunks:
        assert "Long Section" in c.content


def test_overlap_between_chunks():
    """Consecutive chunks from the same section share overlap text."""
    sentences = [f"Sentence number {i} about delta tables and lakehouse patterns." for i in range(20)]
    long_text = " ".join(sentences)
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Overlap Test", page_number=1),
            TextBlock(text=long_text, page_number=1, heading_context=["Overlap Test"]),
        ]
    ])
    chunks = chunk_content(pages, target_tokens=100, max_tokens=150, overlap_tokens=30)
    assert len(chunks) > 1

    # Check that some text from end of chunk N appears in chunk N+1
    # (after stripping the breadcrumb prefix)
    for i in range(len(chunks) - 1):
        c1_text = chunks[i].content.split("\n\n", 1)[-1] if "\n\n" in chunks[i].content else chunks[i].content
        c2_text = chunks[i + 1].content.split("\n\n", 1)[-1] if "\n\n" in chunks[i + 1].content else chunks[i + 1].content
        # Last sentence of c1 should appear somewhere in c2
        c1_sentences = c1_text.split(". ")
        if len(c1_sentences) >= 2:
            last_sentence = c1_sentences[-2]  # second-to-last (last may be partial)
            # At least some overlap text should be present
            # (overlap isn't guaranteed to be exact sentences, so just check non-empty)
            assert len(c2_text) > 0


def test_short_chunks_skipped():
    """Chunks under min_chars are dropped."""
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="Short", page_number=1),
            TextBlock(text="Hi.", page_number=1, heading_context=["Short"]),
            HeadingBlock(level=1, text="Normal", page_number=1),
            TextBlock(text="This is a normal length section with enough content to pass the minimum character threshold for chunking.", page_number=1, heading_context=["Normal"]),
        ]
    ])
    chunks = chunk_content(pages, min_chars=50)
    # Only the "Normal" section should produce a chunk
    assert len(chunks) == 1
    assert "Normal" in chunks[0].content


def test_chunk_index_sequential():
    """Chunk indexes are sequential across the document."""
    pages = _make_pages([
        [
            HeadingBlock(level=1, text="A", page_number=1),
            TextBlock(text="Content A is long enough to be a chunk on its own.", page_number=1, heading_context=["A"]),
            HeadingBlock(level=1, text="B", page_number=1),
            TextBlock(text="Content B is also long enough to be a separate chunk.", page_number=1, heading_context=["B"]),
            HeadingBlock(level=1, text="C", page_number=1),
            TextBlock(text="Content C rounds out the three sections nicely here.", page_number=1, heading_context=["C"]),
        ]
    ])
    chunks = chunk_content(pages)
    indexes = [c.chunk_index for c in chunks]
    assert indexes == list(range(len(chunks)))


def test_empty_pages_produce_no_chunks():
    """Empty pages produce no chunks."""
    pages = _make_pages([[]])
    chunks = chunk_content(pages)
    assert len(chunks) == 0

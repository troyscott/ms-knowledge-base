"""Heading-aware semantic chunking."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from ms_knowledge_base.ingest.pdf_reader import HeadingBlock, PageContent, TextBlock


@dataclass(slots=True)
class Chunk:
    content: str
    section_title: str
    heading_breadcrumb: list[str]
    page_number: int
    chunk_index: int
    char_count: int
    token_estimate: int


# Sentence boundary regex — split after sentence-ending punctuation followed by space
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def chunk_content(
    pages: list[PageContent],
    target_tokens: int = 400,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
    min_chars: int = 50,
) -> list[Chunk]:
    """Split page content into semantic chunks."""
    sections = _split_into_sections(pages)
    chunks: list[Chunk] = []
    chunk_index = 0
    prev_overlap = ""

    for section in sections:
        section_text = section["text"].strip()
        if len(section_text) < min_chars:
            continue

        breadcrumb = section["heading_breadcrumb"]
        section_title = section["section_title"]
        page_number = section["page_number"]

        # Build the breadcrumb prefix for embedding context
        breadcrumb_prefix = ""
        if breadcrumb:
            breadcrumb_prefix = "# " + " > ".join(breadcrumb) + "\n\n"

        token_est = _estimate_tokens(section_text)

        if token_est <= max_tokens:
            # Section fits in one chunk
            content = breadcrumb_prefix + section_text
            if len(content.strip()) >= min_chars:
                chunks.append(Chunk(
                    content=content,
                    section_title=section_title,
                    heading_breadcrumb=list(breadcrumb),
                    page_number=page_number,
                    chunk_index=chunk_index,
                    char_count=len(content),
                    token_estimate=_estimate_tokens(content),
                ))
                chunk_index += 1
            prev_overlap = _get_overlap_text(section_text, overlap_tokens)
        else:
            # Split at sentence boundaries
            sentences = _SENTENCE_SPLIT.split(section_text)
            current_text = prev_overlap
            current_page = page_number

            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue

                candidate = (current_text + " " + sentence).strip() if current_text else sentence
                candidate_tokens = _estimate_tokens(candidate)

                if candidate_tokens > max_tokens and current_text:
                    # Emit current chunk
                    content = breadcrumb_prefix + current_text
                    if len(content.strip()) >= min_chars:
                        chunks.append(Chunk(
                            content=content,
                            section_title=section_title,
                            heading_breadcrumb=list(breadcrumb),
                            page_number=current_page,
                            chunk_index=chunk_index,
                            char_count=len(content),
                            token_estimate=_estimate_tokens(content),
                        ))
                        chunk_index += 1

                    # Start new chunk with overlap
                    overlap = _get_overlap_text(current_text, overlap_tokens)
                    current_text = (overlap + " " + sentence).strip() if overlap else sentence
                    current_page = page_number
                else:
                    current_text = candidate

            # Emit remaining text
            if current_text and len(current_text.strip()) >= min_chars:
                content = breadcrumb_prefix + current_text
                chunks.append(Chunk(
                    content=content,
                    section_title=section_title,
                    heading_breadcrumb=list(breadcrumb),
                    page_number=current_page,
                    chunk_index=chunk_index,
                    char_count=len(content),
                    token_estimate=_estimate_tokens(content),
                ))
                chunk_index += 1

            prev_overlap = _get_overlap_text(current_text, overlap_tokens) if current_text else ""

    return chunks


def _split_into_sections(pages: list[PageContent]) -> list[dict]:
    """Split pages into sections, where each heading starts a new section."""
    sections: list[dict] = []
    current_section: dict | None = None
    heading_stack: list[str] = []

    for page in pages:
        for block in page.blocks:
            if isinstance(block, HeadingBlock):
                # Save current section
                if current_section and current_section["text"].strip():
                    sections.append(current_section)

                # Update heading stack
                while len(heading_stack) >= block.level:
                    heading_stack.pop()
                heading_stack.append(block.text)

                current_section = {
                    "text": "",
                    "section_title": block.text,
                    "heading_breadcrumb": list(heading_stack),
                    "page_number": block.page_number,
                }
            elif isinstance(block, TextBlock):
                if current_section is None:
                    current_section = {
                        "text": "",
                        "section_title": "",
                        "heading_breadcrumb": list(heading_stack),
                        "page_number": block.page_number,
                    }
                current_section["text"] += block.text + "\n"

    # Don't forget last section
    if current_section and current_section["text"].strip():
        sections.append(current_section)

    return sections


def _estimate_tokens(text: str) -> int:
    """Estimate token count: roughly 1 token per 4 characters."""
    return len(text) // 4


def _get_overlap_text(text: str, overlap_tokens: int) -> str:
    """Get the last N tokens worth of text for overlap."""
    target_chars = overlap_tokens * 4
    if len(text) <= target_chars:
        return text
    # Find a sentence boundary near the target
    tail = text[-target_chars:]
    # Try to start at a sentence boundary
    match = re.search(r"(?<=[.!?])\s+", tail)
    if match:
        return tail[match.end():]
    return tail

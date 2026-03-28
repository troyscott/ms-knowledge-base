"""PDF extraction with PyMuPDF, preserving heading hierarchy."""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import fitz


@dataclass(slots=True)
class HeadingBlock:
    level: int  # 1=H1, 2=H2, 3=H3
    text: str
    page_number: int


@dataclass(slots=True)
class TextBlock:
    text: str
    page_number: int
    heading_context: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PageContent:
    page_number: int
    blocks: list[HeadingBlock | TextBlock] = field(default_factory=list)


def extract_pdf(file_path: Path) -> list[PageContent]:
    """Extract structured content from a PDF file."""
    doc = fitz.open(str(file_path))
    try:
        font_stats = _analyze_fonts(doc)
        repeated = _detect_repeated_text(doc)
        pages = []
        heading_stack: list[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_content = PageContent(page_number=page_num + 1)
            blocks_data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

            for block in blocks_data.get("blocks", []):
                if block.get("type") != 0:  # skip image blocks
                    continue

                for line in block.get("lines", []):
                    line_text = ""
                    line_size = 0.0
                    line_bold = True
                    span_count = 0

                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        line_text += text + " "
                        line_size = max(line_size, span.get("size", 0))
                        if "bold" not in span.get("font", "").lower():
                            line_bold = False
                        span_count += 1

                    line_text = line_text.strip()
                    if not line_text:
                        continue

                    # Skip repeated headers/footers
                    if line_text in repeated:
                        continue

                    heading_level = _classify_heading(
                        line_text, line_size, line_bold, font_stats
                    )

                    if heading_level:
                        heading_block = HeadingBlock(
                            level=heading_level,
                            text=line_text,
                            page_number=page_num + 1,
                        )
                        page_content.blocks.append(heading_block)
                        # Update heading stack
                        _update_heading_stack(heading_stack, heading_level, line_text)
                    else:
                        text_block = TextBlock(
                            text=line_text,
                            page_number=page_num + 1,
                            heading_context=list(heading_stack),
                        )
                        page_content.blocks.append(text_block)

            pages.append(page_content)
        return pages
    finally:
        doc.close()


def _analyze_fonts(doc: fitz.Document) -> dict:
    """Analyze font sizes across the document to determine body text size."""
    size_counter: Counter[float] = Counter()

    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in blocks.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if len(text) > 5:  # only count substantial text
                        size = round(span.get("size", 0), 1)
                        size_counter[size] += len(text)

    if not size_counter:
        return {"body_size": 12.0}

    body_size = size_counter.most_common(1)[0][0]
    return {"body_size": body_size}


def _detect_repeated_text(doc: fitz.Document) -> set[str]:
    """Detect text that appears on many pages (headers/footers)."""
    if len(doc) < 3:
        return set()

    page_texts: dict[str, int] = {}
    for page in doc:
        seen_on_page: set[str] = set()
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        for block in blocks.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = ""
                for span in line.get("spans", []):
                    text += span.get("text", "").strip() + " "
                text = text.strip()
                if text and len(text) < 100 and text not in seen_on_page:
                    seen_on_page.add(text)
                    page_texts[text] = page_texts.get(text, 0) + 1

    threshold = max(3, len(doc) * 0.5)
    return {text for text, count in page_texts.items() if count >= threshold}


def _classify_heading(
    text: str, font_size: float, is_bold: bool, font_stats: dict
) -> int | None:
    """Classify a line as a heading level or None (body text)."""
    body_size = font_stats["body_size"]

    # Very short text that looks like a page number
    if len(text) < 3 and text.isdigit():
        return None

    # H1: significantly larger than body
    if font_size >= body_size * 1.4:
        return 1

    # H2: moderately larger
    if font_size >= body_size * 1.15:
        return 2

    # H3: bold text at near-body size, short standalone line
    if is_bold and font_size >= body_size * 0.95 and len(text) < 120:
        return 3

    return None


def _update_heading_stack(
    stack: list[str], level: int, text: str
) -> None:
    """Update the heading breadcrumb stack when a new heading is encountered."""
    # Trim stack to parent level, then add new heading
    while len(stack) >= level:
        stack.pop()
    stack.append(text)

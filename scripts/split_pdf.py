"""Split large PDFs by TOC headings for manageable ingestion."""

import logging
import re
import sys
from pathlib import Path

import click
import fitz

logger = logging.getLogger(__name__)

# Default threshold: split sections larger than this many pages
DEFAULT_MAX_PAGES = 500


def slugify(text: str) -> str:
    """Convert a heading title to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def _resolve_page_ranges(toc: list[list], page_count: int) -> list[dict]:
    """Walk the TOC and resolve each entry to a concrete (start, end) range.

    For entries with p=-1, the start is inherited from the first descendant
    with a valid page. The end is always the start of the next entry at the
    same or higher level.
    """
    resolved: list[dict] = []

    for i, (level, title, page) in enumerate(toc):
        # Find start: use own page, or first valid page from subsequent entries
        start = page if page > 0 else None
        if start is None:
            for j in range(i + 1, len(toc)):
                if toc[j][2] > 0:
                    start = toc[j][2]
                    break

        # Find end: next entry at same or higher (lower number) level
        end = None
        for j in range(i + 1, len(toc)):
            if toc[j][0] <= level:
                # Use that entry's resolved start page
                if toc[j][2] > 0:
                    end = toc[j][2]
                else:
                    for k in range(j + 1, len(toc)):
                        if toc[k][2] > 0:
                            end = toc[k][2]
                            break
                break

        if start is None:
            continue

        resolved.append({
            "level": level,
            "title": title,
            "start": start,
            "end": end or page_count + 1,
        })

    return resolved


def get_section_ranges(
    toc: list[list], page_count: int, max_pages: int
) -> list[dict]:
    """Build split plan: level-1 sections, sub-splitting oversized ones."""
    if not toc:
        return []

    all_resolved = _resolve_page_ranges(toc, page_count)

    # Collect level-1 sections
    level1 = [r for r in all_resolved if r["level"] == 1]

    final_sections: list[dict] = []
    for section in level1:
        page_span = section["end"] - section["start"]

        if page_span > max_pages:
            # Find level-2 children within this section's range
            children = [
                r for r in all_resolved
                if r["level"] == 2
                and r["start"] >= section["start"]
                and r["start"] < section["end"]
            ]

            if children:
                for child in children:
                    # Clamp child end to parent end
                    child_end = min(child["end"], section["end"])
                    child_span = child_end - child["start"]

                    if child_span > max_pages:
                        # Sub-split at level 3
                        grandchildren = [
                            r for r in all_resolved
                            if r["level"] == 3
                            and r["start"] >= child["start"]
                            and r["start"] < child_end
                        ]
                        if grandchildren:
                            for gc in grandchildren:
                                gc_end = min(gc["end"], child_end)
                                final_sections.append({
                                    "title": f'{section["title"]} - {child["title"]} - {gc["title"]}',
                                    "start": gc["start"],
                                    "end": gc_end,
                                })
                        else:
                            final_sections.append({
                                "title": f'{section["title"]} - {child["title"]}',
                                "start": child["start"],
                                "end": child_end,
                            })
                    else:
                        final_sections.append({
                            "title": f'{section["title"]} - {child["title"]}',
                            "start": child["start"],
                            "end": child_end,
                        })
            else:
                final_sections.append(section)
        else:
            final_sections.append(section)

    # Filter out empty sections
    final_sections = [s for s in final_sections if s["end"] - s["start"] > 0]

    return final_sections


def split_pdf(
    input_path: Path,
    output_dir: Path | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    dry_run: bool = False,
    skip_patterns: list[str] | None = None,
) -> list[Path]:
    """Split a PDF into smaller files by TOC sections.

    Returns list of output file paths created.
    """
    doc = fitz.open(str(input_path))
    toc = doc.get_toc()

    if not toc:
        logger.warning("No TOC found in %s — cannot split", input_path.name)
        doc.close()
        return []

    out_dir = output_dir or input_path.parent
    stem = input_path.stem
    sections = get_section_ranges(toc, doc.page_count, max_pages)

    # Filter out sections matching skip patterns
    if skip_patterns:
        filtered = []
        for section in sections:
            slug = slugify(section["title"])
            skipped = False
            for pattern in skip_patterns:
                if re.search(pattern, slug):
                    skipped = True
                    break
            if skipped:
                click.echo(f"  SKIP: {slug} ({section['end'] - section['start']} pages)")
            else:
                filtered.append(section)
        sections = filtered

    if not sections:
        logger.warning("No sections found in TOC")
        doc.close()
        return []

    click.echo(f"\n{input_path.name}: {doc.page_count} pages, {len(sections)} sections")
    click.echo("-" * 60)

    output_files: list[Path] = []
    seen_names: dict[str, int] = {}
    for section in sections:
        start = section["start"] - 1  # fitz uses 0-based
        end = section["end"] - 1
        pages = end - start
        slug = slugify(section["title"])

        # Deduplicate filenames
        if slug in seen_names:
            seen_names[slug] += 1
            slug = f"{slug}-{seen_names[slug]}"
        else:
            seen_names[slug] = 1

        out_name = f"{stem}--{slug}.pdf"
        out_path = out_dir / out_name

        click.echo(f"  {out_name} ({pages} pages)")

        if not dry_run:
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
            new_doc.save(str(out_path))
            new_doc.close()
            output_files.append(out_path)

    doc.close()

    if not dry_run:
        click.echo(f"\nWrote {len(output_files)} files to {out_dir}")
    else:
        click.echo(f"\nDry run: would write {len(sections)} files to {out_dir}")

    return output_files


@click.command()
@click.option("--file", "file_path", required=True, type=click.Path(exists=True, path_type=Path), help="PDF to split")
@click.option("--output-dir", type=click.Path(path_type=Path), default=None, help="Output directory (default: same as input)")
@click.option("--max-pages", type=int, default=DEFAULT_MAX_PAGES, help=f"Max pages per section before sub-splitting (default: {DEFAULT_MAX_PAGES})")
@click.option("--dry-run", is_flag=True, help="Preview splits without writing files")
@click.option("--delete-original", is_flag=True, help="Delete the original PDF after splitting")
@click.option("--skip", multiple=True, help="Regex patterns for section slugs to skip (e.g., 'api-sdk.*rest-api')")
@click.option("--skip-api-ref", is_flag=True, help="Skip API/SDK reference sections (large, low-value for semantic search)")
def main(
    file_path: Path,
    output_dir: Path | None,
    max_pages: int,
    dry_run: bool,
    delete_original: bool,
    skip: tuple[str, ...],
    skip_api_ref: bool,
) -> None:
    """Split a large PDF into smaller files by TOC headings."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    skip_patterns = list(skip)
    if skip_api_ref:
        skip_patterns.extend([
            r"api-sdk.*rest-api",
            r"api-sdk.*v1-api",
            r"api-sdk.*previous-versions",
        ])

    output_files = split_pdf(file_path, output_dir, max_pages, dry_run, skip_patterns or None)

    if output_files and delete_original and not dry_run:
        file_path.unlink()
        click.echo(f"Deleted original: {file_path.name}")


if __name__ == "__main__":
    main()

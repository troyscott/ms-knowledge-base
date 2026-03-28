"""Ingestion pipeline orchestrator with incremental logic."""

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ms_knowledge_base.db.operations import (
    delete_chunks_for_source,
    get_source_by_path,
    insert_chunk,
    insert_embedding,
    insert_source,
    update_source_chunk_count,
    update_source_hash,
)
from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.ingest.chunker import Chunk, chunk_content
from ms_knowledge_base.ingest.embedder import Embedder
from ms_knowledge_base.ingest.pdf_reader import extract_pdf

logger = logging.getLogger(__name__)

# Import settings
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "config"))
from settings import (
    CHUNK_MAX_TOKENS,
    CHUNK_MIN_CHARS,
    CHUNK_OVERLAP_TOKENS,
    CHUNK_TARGET_TOKENS,
    CONTENT_DIR,
    SOURCE_TYPE_MAP,
    TOPIC_KEYWORDS,
)


@dataclass(slots=True)
class IngestResult:
    file_path: Path
    chunks_created: int
    chunks_skipped: int
    source_type: str
    topics_found: list[str]
    errors: list[str] = field(default_factory=list)


def ingest_file(
    file_path: Path,
    db_path: Path,
    embedder: Embedder,
    source_type: str | None = None,
    force: bool = False,
) -> IngestResult:
    """Ingest a single file into the knowledge base."""
    file_path = file_path.resolve()
    file_key = str(file_path)

    # Compute hash
    file_hash = _compute_file_hash(file_path)

    # Determine source type
    if source_type is None:
        source_type = _infer_source_type(file_path)

    conn = get_connection(db_path)
    try:
        existing = get_source_by_path(conn, file_key)

        if existing and existing["file_hash"] == file_hash and not force:
            logger.info("Skipping %s (unchanged)", file_path.name)
            return IngestResult(
                file_path=file_path,
                chunks_created=0,
                chunks_skipped=existing["chunk_count"],
                source_type=source_type,
                topics_found=[],
            )

        # Extract and chunk
        logger.info("Extracting %s", file_path.name)
        pages = extract_pdf(file_path)

        logger.info("Chunking %s", file_path.name)
        chunks = chunk_content(
            pages,
            target_tokens=CHUNK_TARGET_TOKENS,
            max_tokens=CHUNK_MAX_TOKENS,
            overlap_tokens=CHUNK_OVERLAP_TOKENS,
            min_chars=CHUNK_MIN_CHARS,
        )

        if not chunks:
            logger.warning("No chunks produced from %s", file_path.name)
            return IngestResult(
                file_path=file_path,
                chunks_created=0,
                chunks_skipped=0,
                source_type=source_type,
                topics_found=[],
                errors=["No chunks produced"],
            )

        # Classify topics
        chunk_topics: list[tuple[str, list[str]]] = []
        for chunk in chunks:
            primary, tags = classify_topic(chunk, file_path)
            chunk_topics.append((primary, tags))

        # Embed all chunks
        logger.info("Embedding %d chunks from %s", len(chunks), file_path.name)
        texts = [c.content for c in chunks]
        embeddings = embedder.embed_batch(texts)

        # Store in database
        if existing:
            logger.info("Re-ingesting %s (hash changed or forced)", file_path.name)
            delete_chunks_for_source(conn, existing["id"])
            update_source_hash(conn, existing["id"], file_hash)
            source_id = existing["id"]
        else:
            source_id = insert_source(conn, file_key, file_hash, source_type)

        topics_found: set[str] = set()
        errors: list[str] = []

        for i, chunk in enumerate(chunks):
            try:
                topic, topic_tags = chunk_topics[i]
                topics_found.add(topic)

                chunk_id = insert_chunk(
                    conn,
                    source_id=source_id,
                    content=chunk.content,
                    section_title=chunk.section_title,
                    heading_breadcrumb=chunk.heading_breadcrumb,
                    topic=topic,
                    topic_tags=topic_tags,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    token_estimate=chunk.token_estimate,
                )
                insert_embedding(conn, chunk_id, embeddings[i])
            except Exception as e:
                errors.append(f"Chunk {i}: {e}")
                logger.error("Error storing chunk %d: %s", i, e)

        update_source_chunk_count(conn, source_id, len(chunks))

        logger.info(
            "Ingested %s: %d chunks, topics: %s",
            file_path.name,
            len(chunks),
            sorted(topics_found),
        )

        return IngestResult(
            file_path=file_path,
            chunks_created=len(chunks),
            chunks_skipped=0,
            source_type=source_type,
            topics_found=sorted(topics_found),
            errors=errors,
        )
    finally:
        conn.close()


def ingest_directory(
    dir_path: Path,
    db_path: Path,
    embedder: Embedder,
    source_type: str | None = None,
    force: bool = False,
) -> list[IngestResult]:
    """Ingest all supported files in a directory tree."""
    results: list[IngestResult] = []
    supported = {".pdf"}

    for file_path in sorted(dir_path.rglob("*")):
        if file_path.suffix.lower() in supported:
            try:
                result = ingest_file(file_path, db_path, embedder, source_type, force)
                results.append(result)
            except Exception as e:
                logger.error("Failed to ingest %s: %s", file_path, e)
                results.append(IngestResult(
                    file_path=file_path,
                    chunks_created=0,
                    chunks_skipped=0,
                    source_type=source_type or "unknown",
                    topics_found=[],
                    errors=[str(e)],
                ))
    return results


def classify_topic(chunk: Chunk, file_path: Path) -> tuple[str, list[str]]:
    """Assign topic(s) based on keyword matching.

    Returns (primary_topic, all_matching_tags).
    """
    content_lower = chunk.content.lower()
    breadcrumb_lower = " ".join(chunk.heading_breadcrumb).lower()
    combined = content_lower + " " + breadcrumb_lower

    matches: list[tuple[str, int]] = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            matches.append((topic, score))

    if not matches:
        # Fallback: infer from directory path
        return _topic_from_path(file_path), []

    # Sort by specificity (longer path = more specific), then by score
    matches.sort(key=lambda m: (len(m[0].split("/")), m[1]), reverse=True)
    primary = matches[0][0]
    all_tags = sorted({m[0] for m in matches})

    return primary, all_tags


def _topic_from_path(file_path: Path) -> str:
    """Infer a generic topic from the file's directory path."""
    parts = file_path.parts
    for part in parts:
        part_lower = part.lower()
        if "fabric" in part_lower:
            return "fabric/general"
        if "purview" in part_lower:
            return "purview/general"
        if "ai" in part_lower:
            return "ai-engineering/general"
    return "general"


def _infer_source_type(file_path: Path) -> str:
    """Map directory name to source type."""
    for part in file_path.parts:
        if part in SOURCE_TYPE_MAP:
            return SOURCE_TYPE_MAP[part]
    return "personal_notes"


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()

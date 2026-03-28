"""CRUD operations for sources and chunks tables."""

import json
import sqlite3
import struct
from pathlib import Path


def insert_source(
    conn: sqlite3.Connection,
    file_path: str,
    file_hash: str,
    source_type: str,
) -> int:
    """Insert a source record and return the source_id."""
    cursor = conn.execute(
        "INSERT INTO sources (file_path, file_hash, source_type) VALUES (?, ?, ?)",
        (file_path, file_hash, source_type),
    )
    conn.commit()
    return cursor.lastrowid


def get_source_by_path(conn: sqlite3.Connection, file_path: str) -> dict | None:
    """Look up a source by its file path."""
    row = conn.execute(
        "SELECT * FROM sources WHERE file_path = ?", (file_path,)
    ).fetchone()
    return dict(row) if row else None


def update_source_hash(
    conn: sqlite3.Connection, source_id: int, file_hash: str
) -> None:
    """Update the file hash for a source."""
    conn.execute(
        "UPDATE sources SET file_hash = ?, ingested_at = CURRENT_TIMESTAMP WHERE id = ?",
        (file_hash, source_id),
    )
    conn.commit()


def update_source_chunk_count(
    conn: sqlite3.Connection, source_id: int, count: int
) -> None:
    """Update the chunk count for a source."""
    conn.execute(
        "UPDATE sources SET chunk_count = ? WHERE id = ?", (count, source_id)
    )
    conn.commit()


def delete_chunks_for_source(conn: sqlite3.Connection, source_id: int) -> None:
    """Delete all chunks and their embeddings for a source.

    Must delete from chunk_embeddings first since virtual tables
    don't honor FK cascades.
    """
    conn.execute(
        "DELETE FROM chunk_embeddings WHERE chunk_id IN "
        "(SELECT id FROM chunks WHERE source_id = ?)",
        (source_id,),
    )
    conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    conn.commit()


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    """Delete a source and all its chunks/embeddings."""
    delete_chunks_for_source(conn, source_id)
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()


def insert_chunk(
    conn: sqlite3.Connection,
    source_id: int,
    content: str,
    section_title: str | None,
    heading_breadcrumb: list[str],
    topic: str,
    topic_tags: list[str],
    page_number: int | None,
    chunk_index: int,
    token_estimate: int,
) -> int:
    """Insert a chunk and return the chunk_id."""
    cursor = conn.execute(
        """INSERT INTO chunks
        (source_id, content, section_title, heading_breadcrumb,
         topic, topic_tags, page_number, chunk_index, token_estimate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            source_id,
            content,
            section_title,
            json.dumps(heading_breadcrumb),
            topic,
            json.dumps(topic_tags),
            page_number,
            chunk_index,
            token_estimate,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def insert_embedding(
    conn: sqlite3.Connection, chunk_id: int, embedding: list[float]
) -> None:
    """Insert an embedding vector for a chunk."""
    blob = serialize_embedding(embedding)
    conn.execute(
        "INSERT INTO chunk_embeddings (chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, blob),
    )
    conn.commit()


def serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a float list to bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def get_chunks_by_source(conn: sqlite3.Connection, source_id: int) -> list[dict]:
    """Get all chunks for a source, ordered by chunk_index."""
    rows = conn.execute(
        "SELECT * FROM chunks WHERE source_id = ? ORDER BY chunk_index",
        (source_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_chunk_context(
    conn: sqlite3.Connection,
    source_file: str,
    chunk_index: int,
    window: int = 2,
) -> list[dict]:
    """Get chunks around a target chunk for expanded context."""
    rows = conn.execute(
        """SELECT c.* FROM chunks c
        JOIN sources s ON c.source_id = s.id
        WHERE s.file_path = ?
          AND c.chunk_index BETWEEN ? AND ?
        ORDER BY c.chunk_index""",
        (source_file, chunk_index - window, chunk_index + window),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_topics(conn: sqlite3.Connection) -> list[dict]:
    """Get all topics with chunk and source counts."""
    rows = conn.execute(
        """SELECT topic,
                  COUNT(*) as chunk_count,
                  COUNT(DISTINCT source_id) as source_count
           FROM chunks
           GROUP BY topic
           ORDER BY topic"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_sources(
    conn: sqlite3.Connection, source_type: str | None = None
) -> list[dict]:
    """List all sources, optionally filtered by type."""
    if source_type:
        rows = conn.execute(
            "SELECT * FROM sources WHERE source_type = ? ORDER BY ingested_at DESC",
            (source_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sources ORDER BY ingested_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_source_topics(conn: sqlite3.Connection, source_id: int) -> list[str]:
    """Get distinct topics for a specific source."""
    rows = conn.execute(
        "SELECT DISTINCT topic FROM chunks WHERE source_id = ? ORDER BY topic",
        (source_id,),
    ).fetchall()
    return [r["topic"] for r in rows]

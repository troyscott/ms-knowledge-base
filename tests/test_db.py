"""Tests for database schema and operations."""

import json

import pytest

from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.db.operations import (
    delete_chunks_for_source,
    delete_source,
    get_all_topics,
    get_chunk_context,
    get_chunks_by_source,
    get_source_by_path,
    get_source_topics,
    get_sources,
    insert_chunk,
    insert_embedding,
    insert_source,
    serialize_embedding,
    update_source_chunk_count,
    update_source_hash,
)


@pytest.fixture
def db(tmp_path):
    """Create a fresh database for each test."""
    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def test_initialize_db_creates_tables(db):
    tables = {
        r[0]
        for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "sources" in tables
    assert "chunks" in tables
    assert "chunks_fts" in tables
    assert "chunk_embeddings" in tables


def test_wal_mode_enabled(db):
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_insert_and_retrieve_source(db):
    sid = insert_source(db, "test.pdf", "abc123", "microsoft_official")
    assert sid is not None

    source = get_source_by_path(db, "test.pdf")
    assert source is not None
    assert source["file_hash"] == "abc123"
    assert source["source_type"] == "microsoft_official"


def test_duplicate_source_path_rejected(db):
    insert_source(db, "test.pdf", "hash1", "microsoft_official")
    with pytest.raises(Exception):
        insert_source(db, "test.pdf", "hash2", "microsoft_official")


def test_update_source_hash(db):
    sid = insert_source(db, "test.pdf", "old_hash", "microsoft_official")
    update_source_hash(db, sid, "new_hash")
    source = get_source_by_path(db, "test.pdf")
    assert source["file_hash"] == "new_hash"


def test_insert_chunk_and_embedding(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    cid = insert_chunk(
        db,
        source_id=sid,
        content="Delta tables are great",
        section_title="Delta Tables",
        heading_breadcrumb=["Fabric", "Lakehouse", "Delta Tables"],
        topic="fabric/lakehouse",
        topic_tags=["fabric/lakehouse", "data-engineering/delta-tables"],
        page_number=1,
        chunk_index=0,
        token_estimate=5,
    )
    assert cid is not None

    # Insert embedding (384-dim random vector)
    embedding = [0.1] * 384
    insert_embedding(db, cid, embedding)

    # Verify embedding exists
    row = db.execute(
        "SELECT * FROM chunk_embeddings WHERE chunk_id = ?", (cid,)
    ).fetchone()
    assert row is not None


def test_fts_sync_after_insert(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    insert_chunk(
        db,
        source_id=sid,
        content="Lakehouse architecture with delta tables",
        section_title="Architecture",
        heading_breadcrumb=["Fabric"],
        topic="fabric/lakehouse",
        topic_tags=["fabric/lakehouse"],
        page_number=1,
        chunk_index=0,
        token_estimate=6,
    )
    # FTS search
    results = db.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'lakehouse'"
    ).fetchall()
    assert len(results) == 1


def test_delete_chunks_for_source(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    cid = insert_chunk(
        db,
        source_id=sid,
        content="Test content",
        section_title="Test",
        heading_breadcrumb=["Test"],
        topic="fabric/lakehouse",
        topic_tags=[],
        page_number=1,
        chunk_index=0,
        token_estimate=2,
    )
    insert_embedding(db, cid, [0.1] * 384)

    delete_chunks_for_source(db, sid)

    chunks = get_chunks_by_source(db, sid)
    assert len(chunks) == 0

    emb = db.execute(
        "SELECT * FROM chunk_embeddings WHERE chunk_id = ?", (cid,)
    ).fetchone()
    assert emb is None


def test_delete_source_cascades(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    cid = insert_chunk(
        db,
        source_id=sid,
        content="Test",
        section_title="Test",
        heading_breadcrumb=[],
        topic="fabric/lakehouse",
        topic_tags=[],
        page_number=1,
        chunk_index=0,
        token_estimate=1,
    )
    insert_embedding(db, cid, [0.1] * 384)

    delete_source(db, sid)

    assert get_source_by_path(db, "test.pdf") is None
    assert len(get_chunks_by_source(db, sid)) == 0


def test_get_all_topics(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    insert_chunk(db, sid, "A", "S", [], "fabric/lakehouse", [], 1, 0, 1)
    insert_chunk(db, sid, "B", "S", [], "fabric/lakehouse", [], 1, 1, 1)
    insert_chunk(db, sid, "C", "S", [], "fabric/warehouse", [], 1, 2, 1)

    topics = get_all_topics(db)
    assert len(topics) == 2
    lake = next(t for t in topics if t["topic"] == "fabric/lakehouse")
    assert lake["chunk_count"] == 2


def test_get_sources_filter(db):
    insert_source(db, "a.pdf", "h1", "microsoft_official")
    insert_source(db, "b.pdf", "h2", "personal_notes")

    all_sources = get_sources(db)
    assert len(all_sources) == 2

    official = get_sources(db, source_type="microsoft_official")
    assert len(official) == 1
    assert official[0]["file_path"] == "a.pdf"


def test_get_chunk_context(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    for i in range(5):
        insert_chunk(db, sid, f"Chunk {i}", "S", [], "fabric/lakehouse", [], 1, i, 1)

    context = get_chunk_context(db, "test.pdf", chunk_index=2, window=1)
    assert len(context) == 3
    indexes = [c["chunk_index"] for c in context]
    assert indexes == [1, 2, 3]


def test_heading_breadcrumb_stored_as_json(db):
    sid = insert_source(db, "test.pdf", "hash", "microsoft_official")
    breadcrumb = ["Fabric", "Lakehouse", "Delta"]
    cid = insert_chunk(
        db, sid, "Content", "Delta", breadcrumb, "fabric/lakehouse", [], 1, 0, 1
    )
    chunk = get_chunks_by_source(db, sid)[0]
    assert json.loads(chunk["heading_breadcrumb"]) == breadcrumb

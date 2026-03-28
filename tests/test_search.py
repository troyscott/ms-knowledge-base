"""Tests for KBSearchEngine."""

import random

import pytest

from ms_knowledge_base.db.operations import insert_chunk, insert_embedding, insert_source
from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.server.search import KBSearchEngine


class MockEmbedder:
    """Mock embedder returning deterministic vectors for testing."""

    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def embed_text(self, text: str) -> list[float]:
        if text not in self._cache:
            rng = random.Random(hash(text))
            vec = [rng.gauss(0, 1) for _ in range(384)]
            # Normalize
            norm = sum(v * v for v in vec) ** 0.5
            self._cache[text] = [v / norm for v in vec]
        return self._cache[text]

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


@pytest.fixture
def search_engine(tmp_path):
    """Create a search engine with a pre-populated test database."""
    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    conn = get_connection(db_path)

    embedder = MockEmbedder()

    # Insert test data
    sid1 = insert_source(conn, "fabric-guide.pdf", "hash1", "microsoft_official")
    sid2 = insert_source(conn, "personal-notes.md", "hash2", "personal_notes")

    test_chunks = [
        (sid1, "# Fabric > Lakehouse > Delta Tables\n\nDelta tables in Microsoft Fabric lakehouse support ACID transactions and time travel.", "Delta Tables", ["Fabric", "Lakehouse", "Delta Tables"], "fabric/lakehouse", 1, 0),
        (sid1, "# Fabric > Lakehouse > Architecture\n\nThe lakehouse architecture combines data warehouse and data lake patterns.", "Architecture", ["Fabric", "Lakehouse", "Architecture"], "fabric/lakehouse", 2, 1),
        (sid1, "# Fabric > Warehouse\n\nFabric warehouse provides T-SQL analytics on structured data.", "Warehouse", ["Fabric", "Warehouse"], "fabric/warehouse", 5, 2),
        (sid1, "# Fabric > Pipelines\n\nData pipelines orchestrate data movement and transformation.", "Pipelines", ["Fabric", "Pipelines"], "fabric/pipelines", 8, 3),
        (sid2, "# Purview > Governance\n\nMicrosoft Purview provides data governance and compliance features.", "Governance", ["Purview", "Governance"], "purview/governance", 1, 0),
    ]

    for sid, content, title, breadcrumb, topic, page, idx in test_chunks:
        cid = insert_chunk(conn, sid, content, title, breadcrumb, topic, [topic], page, idx, len(content) // 4)
        embedding = embedder.embed_text(content)
        insert_embedding(conn, cid, embedding)

    conn.close()

    engine = KBSearchEngine(db_path, embedder)
    yield engine
    engine.close()


def test_search_returns_results(search_engine):
    """Basic search returns results."""
    results = search_engine.search("lakehouse delta tables")
    assert len(results) > 0


def test_search_relevance_ordering(search_engine):
    """Results are ordered by relevance score descending."""
    results = search_engine.search("delta tables ACID transactions", max_results=5)
    scores = [r.relevance_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_topic_filter_narrows_results(search_engine):
    """Filtering by topic prefix excludes non-matching results."""
    results = search_engine.search("data", topic_filter="fabric/lakehouse")
    for r in results:
        assert r.topic.startswith("fabric/lakehouse")


def test_source_type_filter(search_engine):
    """Filtering by source_type excludes other types."""
    results = search_engine.search("governance data", source_type="personal_notes")
    for r in results:
        assert r.source_type == "personal_notes"


def test_empty_query_returns_empty(search_engine):
    """Empty string query returns no results."""
    results = search_engine.search("")
    assert len(results) == 0


def test_max_results_respected(search_engine):
    """Result count does not exceed max_results."""
    results = search_engine.search("fabric", max_results=2)
    assert len(results) <= 2


def test_list_topics(search_engine):
    """list_topics returns all topics with counts."""
    topics = search_engine.list_topics()
    assert len(topics) > 0
    topic_names = {t.topic for t in topics}
    assert "fabric/lakehouse" in topic_names
    assert "purview/governance" in topic_names


def test_get_source_info(search_engine):
    """get_source_info returns source documents."""
    sources = search_engine.get_source_info()
    assert len(sources) == 2
    names = {s.file_name for s in sources}
    assert "fabric-guide.pdf" in names


def test_get_source_info_filtered(search_engine):
    """get_source_info with filter returns only matching type."""
    sources = search_engine.get_source_info(source_type="personal_notes")
    assert len(sources) == 1
    assert sources[0].file_name == "personal-notes.md"


def test_get_chunk_context(search_engine):
    """get_chunk_context returns surrounding chunks."""
    context = search_engine.get_chunk_context("fabric-guide.pdf", chunk_index=1, window=1)
    assert len(context) >= 2
    indexes = [c.chunk_index for c in context]
    assert 1 in indexes
    target = next(c for c in context if c.is_target)
    assert target.chunk_index == 1

"""Integration tests — full pipeline round-trip."""

import time
from pathlib import Path

import fitz
import pytest

from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.ingest.embedder import Embedder
from ms_knowledge_base.ingest.pipeline import ingest_file
from ms_knowledge_base.server.search import KBSearchEngine


@pytest.fixture(scope="module")
def test_pdf(tmp_path_factory) -> Path:
    """Generate a small test PDF with known content."""
    pdf_path = tmp_path_factory.mktemp("fixtures") / "test_fabric_guide.pdf"
    doc = fitz.open()

    # Page 1: Lakehouse content
    page1 = doc.new_page()
    # Title (large font)
    page1.insert_text((72, 80), "Microsoft Fabric Fundamentals", fontsize=24)
    # H2
    page1.insert_text((72, 130), "Lakehouse Architecture", fontsize=16)
    # Body
    body1 = (
        "The Microsoft Fabric lakehouse is a unified analytics platform that combines "
        "the flexibility of a data lake with the performance of a data warehouse. "
        "It uses Delta tables as its native storage format, providing ACID transactions, "
        "time travel, and schema enforcement. The lakehouse supports both batch and "
        "streaming workloads through Apache Spark integration. Data engineers can use "
        "notebooks to transform data using PySpark or Spark SQL, while analysts can "
        "query data using T-SQL through the SQL analytics endpoint."
    )
    rect1 = fitz.Rect(72, 150, 540, 600)
    page1.insert_textbox(rect1, body1, fontsize=11)

    # Page 2: Warehouse content
    page2 = doc.new_page()
    page2.insert_text((72, 80), "Fabric Warehouse", fontsize=16)
    body2 = (
        "The Fabric warehouse is a fully managed SQL analytics engine that provides "
        "enterprise-grade data warehousing capabilities. It supports T-SQL for querying "
        "and stored procedures for complex transformations. The warehouse integrates "
        "seamlessly with Power BI for reporting and supports cross-database queries "
        "with the lakehouse through shortcuts. The warehouse uses a columnar storage "
        "format optimized for analytical queries and provides automatic performance "
        "tuning through intelligent query processing."
    )
    rect2 = fitz.Rect(72, 100, 540, 500)
    page2.insert_textbox(rect2, body2, fontsize=11)

    # Page 3: Governance
    page3 = doc.new_page()
    page3.insert_text((72, 80), "Data Governance with Purview", fontsize=16)
    body3 = (
        "Microsoft Purview provides comprehensive data governance capabilities for "
        "Fabric workspaces. It offers data catalog features for discovering and "
        "understanding data assets across the organization. Sensitivity labels can be "
        "applied to protect confidential information. Data lineage tracking shows how "
        "data flows through pipelines and transformations, enabling impact analysis "
        "when changes are planned. Purview governance policies help ensure compliance "
        "with organizational and regulatory requirements."
    )
    rect3 = fitz.Rect(72, 100, 540, 500)
    page3.insert_textbox(rect3, body3, fontsize=11)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture(scope="module")
def embedder():
    """Load the real embedding model (shared across module tests)."""
    return Embedder("all-MiniLM-L6-v2")


@pytest.fixture(scope="module")
def populated_db(tmp_path_factory, test_pdf, embedder):
    """Ingest the test PDF into a fresh database."""
    db_path = tmp_path_factory.mktemp("data") / "integration.db"
    initialize_db(db_path)
    result = ingest_file(test_pdf, db_path, embedder, source_type="microsoft_official")
    assert result.chunks_created > 0
    assert len(result.errors) == 0
    return db_path, result


@pytest.fixture(scope="module")
def engine(populated_db, embedder):
    """Create a search engine over the populated database."""
    db_path, _ = populated_db
    eng = KBSearchEngine(db_path, embedder)
    yield eng
    eng.close()


def test_ingestion_creates_chunks(populated_db):
    """Ingestion produces chunks from the test PDF."""
    _, result = populated_db
    assert result.chunks_created > 0
    assert result.source_type == "microsoft_official"


def test_ingestion_assigns_topics(populated_db):
    """Ingestion assigns relevant topics."""
    _, result = populated_db
    assert len(result.topics_found) > 0


def test_search_lakehouse_returns_relevant(engine):
    """Searching for 'lakehouse' returns lakehouse-related content."""
    results = engine.search("lakehouse delta tables")
    assert len(results) > 0
    # At least one result should mention lakehouse
    contents = " ".join(r.content.lower() for r in results)
    assert "lakehouse" in contents


def test_search_warehouse_returns_relevant(engine):
    """Searching for 'warehouse T-SQL' returns warehouse content."""
    results = engine.search("warehouse T-SQL analytics")
    assert len(results) > 0
    contents = " ".join(r.content.lower() for r in results)
    assert "warehouse" in contents


def test_search_governance_returns_relevant(engine):
    """Searching for 'governance' returns Purview content."""
    results = engine.search("data governance compliance Purview")
    assert len(results) > 0
    contents = " ".join(r.content.lower() for r in results)
    assert "governance" in contents or "purview" in contents


def test_topic_filter_works(engine):
    """Topic filter excludes non-matching results."""
    results = engine.search("data", topic_filter="fabric/lakehouse")
    for r in results:
        assert r.topic.startswith("fabric/lakehouse")


def test_search_latency_under_200ms(engine):
    """Search completes in under 200ms."""
    # Warm up
    engine.search("test warmup")

    start = time.perf_counter()
    engine.search("lakehouse delta tables architecture")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 200, f"Search took {elapsed_ms:.1f}ms (limit: 200ms)"


def test_incremental_skip(test_pdf, populated_db, embedder):
    """Re-ingesting the same file skips it."""
    db_path, _ = populated_db
    result = ingest_file(test_pdf, db_path, embedder)
    assert result.chunks_created == 0
    assert result.chunks_skipped > 0


def test_force_reingestion(test_pdf, populated_db, embedder):
    """Force flag re-ingests even when hash matches."""
    db_path, original = populated_db
    result = ingest_file(test_pdf, db_path, embedder, force=True)
    assert result.chunks_created > 0


def test_list_topics_returns_data(engine):
    """list_topics shows topics from ingested content."""
    topics = engine.list_topics()
    assert len(topics) > 0


def test_get_source_info_returns_data(engine):
    """get_source_info lists the ingested document."""
    sources = engine.get_source_info()
    assert len(sources) == 1
    assert sources[0].chunk_count > 0


def test_chunk_context_window(engine):
    """get_chunk_context returns chunks around the target."""
    context = engine.get_chunk_context("test_fabric_guide.pdf", chunk_index=0, window=2)
    assert len(context) >= 1
    assert any(c.is_target for c in context)

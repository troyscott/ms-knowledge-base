"""Tests for MCP tool registration."""

import random

import pytest

from fastmcp import FastMCP

from ms_knowledge_base.db.operations import insert_chunk, insert_embedding, insert_source
from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.server.search import KBSearchEngine
from ms_knowledge_base.server.tools import register_tools


class MockEmbedder:
    """Mock embedder for tool tests."""

    def embed_text(self, text: str) -> list[float]:
        rng = random.Random(hash(text))
        vec = [rng.gauss(0, 1) for _ in range(384)]
        norm = sum(v * v for v in vec) ** 0.5
        return [v / norm for v in vec]

    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


@pytest.fixture
def mcp_server(tmp_path):
    """Create a FastMCP server with tools registered."""
    db_path = tmp_path / "test.db"
    initialize_db(db_path)
    conn = get_connection(db_path)

    embedder = MockEmbedder()

    sid = insert_source(conn, "test.pdf", "hash", "microsoft_official")
    content = "# Fabric > Lakehouse\n\nDelta tables support ACID transactions in lakehouse."
    cid = insert_chunk(conn, sid, content, "Lakehouse", ["Fabric", "Lakehouse"],
                       "fabric/lakehouse", ["fabric/lakehouse"], 1, 0, len(content) // 4)
    insert_embedding(conn, cid, embedder.embed_text(content))
    conn.close()

    engine = KBSearchEngine(db_path, embedder)
    mcp = FastMCP("Test KB")
    register_tools(mcp, engine)

    yield mcp
    engine.close()


@pytest.mark.asyncio
async def test_tools_registered(mcp_server):
    """All 4 tools are registered on the MCP server."""
    tools = await mcp_server.list_tools()
    tool_names = {t.name for t in tools}
    assert "search_kb" in tool_names
    assert "list_topics" in tool_names
    assert "get_chunk_context" in tool_names
    assert "get_source_info" in tool_names


@pytest.mark.asyncio
async def test_tool_count(mcp_server):
    """Exactly 4 tools registered."""
    tools = await mcp_server.list_tools()
    assert len(tools) == 4

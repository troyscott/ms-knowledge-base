"""MCP tool definitions for the knowledge base server."""

from dataclasses import asdict

from fastmcp import FastMCP

from ms_knowledge_base.server.search import KBSearchEngine


def register_tools(mcp: FastMCP, engine: KBSearchEngine) -> None:
    """Register all KB tools on the MCP server."""

    @mcp.tool()
    def search_kb(
        query: str,
        topic_filter: str | None = None,
        source_type: str | None = None,
        max_results: int = 5,
    ) -> list[dict]:
        """Search the Microsoft knowledge base for relevant content on Fabric, Data Engineering, AI Engineering, Purview, and related topics.

        Args:
            query: Natural language search query
            topic_filter: Optional topic prefix to narrow results (e.g., "fabric/iq" matches all IQ subtopics)
            source_type: Optional filter by source type (microsoft_official, microsoft_sample, fabcon_notes, personal_notes)
            max_results: Number of results to return (1-10, default 5)
        """
        results = engine.search(query, topic_filter, source_type, max_results)
        return [asdict(r) for r in results]

    @mcp.tool()
    def list_topics() -> list[dict]:
        """List all available topics in the knowledge base with chunk counts."""
        topics = engine.list_topics()
        return [asdict(t) for t in topics]

    @mcp.tool()
    def get_chunk_context(
        source_file: str,
        chunk_index: int,
        window: int = 2,
    ) -> list[dict]:
        """Retrieve chunks before and after a specific chunk for expanded context.

        Args:
            source_file: Filename of the source document
            chunk_index: Index of the target chunk
            window: Number of chunks before and after to include (default 2)
        """
        chunks = engine.get_chunk_context(source_file, chunk_index, window)
        return [asdict(c) for c in chunks]

    @mcp.tool()
    def get_source_info(
        source_type: str | None = None,
    ) -> list[dict]:
        """List ingested documents in the knowledge base.

        Args:
            source_type: Optional filter (microsoft_official, microsoft_sample, fabcon_notes, personal_notes)
        """
        sources = engine.get_source_info(source_type)
        return [asdict(s) for s in sources]

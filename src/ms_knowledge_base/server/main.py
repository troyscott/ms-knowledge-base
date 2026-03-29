"""MCP server entry point with dual transport and auth."""

import argparse
import logging
import sys
from pathlib import Path

from fastmcp import FastMCP

# Import settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "config"))
from settings import DB_PATH, EMBEDDING_MODEL, SSE_DEFAULT_HOST, SSE_DEFAULT_PORT

from ms_knowledge_base.ingest.embedder import Embedder
from ms_knowledge_base.server.auth import create_auth_middleware
from ms_knowledge_base.server.search import KBSearchEngine
from ms_knowledge_base.server.tools import register_tools

logger = logging.getLogger(__name__)


def create_server(db_path: Path, embedder: Embedder) -> FastMCP:
    """Create and configure the MCP server."""
    mcp = FastMCP(
        "Microsoft Knowledge Base",
        instructions=(
            "Semantic search over curated Microsoft Fabric, "
            "Data Engineering, and AI Engineering content."
        ),
    )

    engine = KBSearchEngine(db_path, embedder)
    register_tools(mcp, engine)

    return mcp


def main() -> None:
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Microsoft Knowledge Base MCP Server")
    parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio",
        help="Transport mode (default: stdio)"
    )
    parser.add_argument("--host", default=SSE_DEFAULT_HOST, help="SSE host")
    parser.add_argument("--port", type=int, default=SSE_DEFAULT_PORT, help="SSE port")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Database path")
    parser.add_argument(
        "--auth", choices=["none", "apikey", "entra"], default="none",
        help="Auth mode (default: none)"
    )
    parser.add_argument("--auth-token", default=None, help="API key for apikey auth mode")
    parser.add_argument("--tenant-id", default=None, help="Entra ID tenant ID")
    parser.add_argument("--client-id", default=None, help="Entra ID app registration client ID")
    args = parser.parse_args()

    if not args.db.exists():
        logger.error("Database not found at %s. Run ingestion first.", args.db)
        sys.exit(1)

    # Load embedding model once
    logger.info("Loading embedding model (%s)...", EMBEDDING_MODEL)
    embedder = Embedder(EMBEDDING_MODEL)
    logger.info("Model loaded.")

    # Create server
    server = create_server(args.db, embedder)

    if args.transport == "stdio":
        logger.info("Starting MCP server (stdio transport)")
        server.run(transport="stdio")
    else:
        # SSE transport
        auth_middleware = create_auth_middleware(
            mode=args.auth,
            api_key=args.auth_token,
            tenant_id=args.tenant_id,
            client_id=args.client_id,
        )

        if auth_middleware:
            logger.info("Auth mode: %s", args.auth)

        logger.info("Starting MCP server (SSE on %s:%d)", args.host, args.port)
        server.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()

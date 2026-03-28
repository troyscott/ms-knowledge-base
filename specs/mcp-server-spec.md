# Microsoft Knowledge Base — MCP Server Specification

## Purpose

Expose the knowledge base as an MCP server with semantic search tools. Designed for minimal per-request compute on the Beelink N100.

---

## Server Configuration

**Framework**: `fastmcp` (Python MCP SDK)

**Transports**:
- **stdio**: For Claude Desktop local integration
- **SSE**: For remote access — Tailscale (personal) or Azure Container Apps (Fabric/enterprise)

**Authentication Modes**:
- **none**: No auth (default for stdio, Tailscale-protected SSE)
- **apikey**: Simple Bearer token check (testing/staging)
- **entra**: Microsoft Entra ID JWT validation (Azure deployment for Fabric access)

**Startup Behavior**:
1. Load embedding model into memory (~300MB, one-time cost)
2. Open SQLite database connection (WAL mode for concurrent reads)
3. Validate sqlite-vec extension is available
4. Initialize auth middleware (if `--auth` is not `none`)
5. Start listening on configured transport

**Shutdown**: Graceful — close DB connection, release model memory.

---

## Tool Definitions

### 1. `search_kb`

**Description**: Search the Microsoft knowledge base for relevant content on Fabric, Data Engineering, AI Engineering, Purview, and related topics.

**Parameters**:
```python
@tool
def search_kb(
    query: str,
    topic_filter: str | None = None,
    source_type: str | None = None,
    max_results: int = 5
) -> list[SearchResult]:
    """
    Semantic search over the Microsoft knowledge base.
    
    Args:
        query: Natural language search query
        topic_filter: Optional topic prefix to narrow results 
                      (e.g., "fabric/iq" matches all IQ subtopics)
        source_type: Optional filter by source type 
                     (microsoft_official, microsoft_sample, fabcon_notes, personal_notes)
        max_results: Number of results to return (1-10, default 5)
    
    Returns:
        List of matching chunks with content, metadata, and relevance score.
    """
```

**Response Schema**:
```python
@dataclass
class SearchResult:
    content: str              # the chunk text
    section_title: str        # heading context
    topic: str                # primary topic
    source_file: str          # original filename (no path)
    source_type: str          # microsoft_official, etc.
    page_number: int | None   # page in source PDF
    relevance_score: float    # cosine similarity (0-1)
```

**Search Strategy** (hybrid, two-phase):
1. **Vector search**: Embed the query with MiniLM, run sqlite-vec KNN search, retrieve top `max_results * 2` candidates
2. **Keyword boost**: Run FTS5 search on the same query, boost any candidates that also appear in FTS results
3. **Filter**: Apply `topic_filter` and `source_type` if provided
4. **Rank**: Re-rank by combined score (0.7 * vector_score + 0.3 * fts_boost), return top `max_results`
5. **Deduplicate**: If consecutive chunks from the same source score highly, merge them into a single result with combined content

**Performance Target**: < 200ms total per query.

---

### 2. `list_topics`

**Description**: List all available topics in the knowledge base with chunk counts.

**Parameters**: None

**Response**:
```python
@dataclass
class TopicInfo:
    topic: str
    chunk_count: int
    source_count: int  # number of distinct source files
```

**Implementation**: Simple SQL aggregation, no embedding needed. Cache result, invalidate on ingestion.

---

### 3. `get_chunk_context`

**Description**: Get surrounding chunks for a specific result to see more context from the same section.

**Parameters**:
```python
@tool
def get_chunk_context(
    source_file: str,
    chunk_index: int,
    window: int = 2
) -> list[ContextChunk]:
    """
    Retrieve chunks before and after a specific chunk for expanded context.
    
    Args:
        source_file: Filename of the source document
        chunk_index: Index of the target chunk
        window: Number of chunks before and after to include (default 2)
    
    Returns:
        Ordered list of chunks around the target, with the target marked.
    """
```

**Use Case**: After `search_kb` returns a relevant chunk, the LLM can call this to get more context without a new embedding query. Very cheap — just a SQL range query.

---

### 4. `get_source_info`

**Description**: List all ingested source documents with their metadata.

**Parameters**:
```python
@tool
def get_source_info(
    source_type: str | None = None
) -> list[SourceInfo]:
    """
    List ingested documents in the knowledge base.
    
    Args:
        source_type: Optional filter (microsoft_official, microsoft_sample, 
                     fabcon_notes, personal_notes)
    
    Returns:
        List of source documents with chunk counts and topics covered.
    """
```

**Response**:
```python
@dataclass
class SourceInfo:
    file_name: str
    source_type: str
    chunk_count: int
    topics: list[str]       # distinct topics found in this source
    ingested_at: str        # ISO timestamp
```

---

## Server Entry Point (`src/server/main.py`)

```python
import argparse
from fastmcp import FastMCP

def create_server() -> FastMCP:
    mcp = FastMCP(
        "Microsoft Knowledge Base",
        description="Semantic search over curated Microsoft Fabric, "
                    "Data Engineering, and AI Engineering content."
    )
    # Register tools
    register_tools(mcp)
    return mcp

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3200)
    parser.add_argument("--db", default="data/knowledge.db")
    parser.add_argument("--auth", choices=["none", "apikey", "entra"], default="none")
    parser.add_argument("--auth-token", default=None, help="API key for apikey auth mode")
    parser.add_argument("--tenant-id", default=None, help="Entra ID tenant ID")
    parser.add_argument("--client-id", default=None, help="Entra ID app registration client ID")
    args = parser.parse_args()
    
    server = create_server()
    
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        # Initialize auth middleware for SSE transport
        auth_middleware = create_auth_middleware(
            mode=args.auth,
            api_key=args.auth_token,
            tenant_id=args.tenant_id,
            client_id=args.client_id
        )
        server.run(transport="sse", host=args.host, port=args.port,
                    middleware=auth_middleware)

if __name__ == "__main__":
    main()
```

---

## Authentication Module (`src/server/auth.py`)

Provides pluggable auth middleware for the SSE transport.

```python
class AuthMode:
    NONE = "none"
    APIKEY = "apikey"
    ENTRA = "entra"

def create_auth_middleware(
    mode: str,
    api_key: str | None = None,
    tenant_id: str | None = None,
    client_id: str | None = None
) -> Callable | None:
    """Factory for auth middleware based on deployment mode."""
    if mode == AuthMode.NONE:
        return None
    elif mode == AuthMode.APIKEY:
        return ApiKeyMiddleware(api_key)
    elif mode == AuthMode.ENTRA:
        return EntraIdMiddleware(tenant_id, client_id)

class ApiKeyMiddleware:
    """Simple Bearer token validation for testing/staging."""
    def __init__(self, expected_token: str):
        self.expected_token = expected_token
    
    def validate(self, request) -> bool:
        auth_header = request.headers.get("Authorization", "")
        return auth_header == f"Bearer {self.expected_token}"

class EntraIdMiddleware:
    """Microsoft Entra ID JWT validation for Azure deployment."""
    def __init__(self, tenant_id: str, client_id: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self._jwks_cache = None
        self._jwks_fetched_at = None
    
    def validate(self, request) -> bool:
        """
        Validate JWT from Authorization: Bearer <token> header.
        
        Checks:
        - Signature via JWKS from login.microsoftonline.com
        - Audience matches client_id
        - Issuer matches tenant_id
        - Token not expired
        
        JWKS keys are cached for 24 hours to avoid per-request fetch.
        """
        ...
    
    def _get_jwks(self) -> dict:
        """Fetch and cache JWKS from Microsoft's OpenID config endpoint."""
        # https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration
        ...
```

**Dependencies for Entra ID auth**: `PyJWT`, `cryptography`, `requests` (already in stack).

---

## Search Implementation (`src/server/search.py`)

```python
class KBSearchEngine:
    def __init__(self, db_path: Path, model_name: str = "all-MiniLM-L6-v2"):
        self.db = sqlite3.connect(str(db_path))
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.enable_load_extension(True)
        # Load sqlite-vec extension
        import sqlite_vec
        self.db.load_extension(sqlite_vec.loadable_path())
        
        # Load embedding model once
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
    
    def search(
        self,
        query: str,
        topic_filter: str | None = None,
        source_type: str | None = None,
        max_results: int = 5
    ) -> list[SearchResult]:
        # 1. Embed the query
        query_embedding = self.model.encode(query, normalize_embeddings=True)
        
        # 2. Vector KNN search via sqlite-vec
        candidates = self._vector_search(query_embedding, max_results * 2)
        
        # 3. FTS keyword boost
        fts_hits = self._fts_search(query)
        
        # 4. Combine scores
        results = self._merge_and_rank(candidates, fts_hits)
        
        # 5. Apply filters
        if topic_filter:
            results = [r for r in results if r.topic.startswith(topic_filter)]
        if source_type:
            results = [r for r in results if r.source_type == source_type]
        
        # 6. Deduplicate consecutive chunks
        results = self._deduplicate_adjacent(results)
        
        return results[:max_results]
    
    def _vector_search(self, embedding, limit):
        """KNN search using sqlite-vec."""
        # sqlite-vec query pattern:
        # SELECT rowid, distance FROM chunk_embeddings
        # WHERE embedding MATCH ? ORDER BY distance LIMIT ?
        ...
    
    def _fts_search(self, query):
        """Full-text search for keyword boosting."""
        # SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ?
        ...
    
    def _merge_and_rank(self, vector_results, fts_results):
        """Combine vector similarity and keyword relevance."""
        # Score = 0.7 * cosine_similarity + 0.3 * fts_boost
        ...
    
    def _deduplicate_adjacent(self, results):
        """Merge consecutive chunks from same source."""
        ...
```

---

## Configuration (`config/settings.py`)

```python
from pathlib import Path

# Paths
DB_PATH = Path("data/knowledge.db")
CONTENT_DIR = Path("content")

# Embedding
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# Chunking
CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHUNK_MIN_CHARS = 50  # skip chunks shorter than this

# Search
DEFAULT_MAX_RESULTS = 5
VECTOR_WEIGHT = 0.7
FTS_WEIGHT = 0.3
CANDIDATE_MULTIPLIER = 2  # fetch N * max_results candidates for re-ranking

# Server
SSE_DEFAULT_PORT = 3200
SSE_DEFAULT_HOST = "0.0.0.0"

# Topic taxonomy (imported from taxonomy module)
```

---

## Error Handling

- **Model load failure**: Exit with clear error message (likely missing sentence-transformers install)
- **Database not found**: Exit with message pointing to ingestion script
- **sqlite-vec not available**: Exit with install instructions
- **Empty query**: Return empty results with helpful message
- **Query too long**: Truncate to 512 tokens (MiniLM max sequence length)
- **No results**: Return empty list with suggestion to broaden search or check available topics

---

## Logging

Use Python `logging` module. Levels:
- **INFO**: Server start/stop, tool calls (query text, result count, latency)
- **WARNING**: Slow queries (>500ms), empty results
- **ERROR**: Database errors, embedding failures
- **DEBUG**: Full query embeddings, SQL queries, score calculations

Log to stderr (for stdio transport compatibility) and optionally to file.

---

## Testing

```python
# tests/test_search.py
def test_search_returns_relevant_results():
    """Search for 'lakehouse delta tables' should return fabric/lakehouse chunks."""

def test_topic_filter_narrows_results():
    """Filtering by 'fabric/iq' should exclude non-IQ results."""

def test_source_type_filter():
    """Filtering by 'microsoft_official' excludes personal notes."""

def test_empty_query_returns_empty():
    """Empty string query returns no results."""

def test_get_chunk_context_returns_window():
    """Context window of 2 returns 5 chunks (2 before, target, 2 after)."""

def test_deduplication_merges_adjacent():
    """Adjacent chunks from same source get merged."""

def test_search_latency_under_200ms():
    """End-to-end search completes in under 200ms."""
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "ms-knowledge-base"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=0.1.0",
    "sentence-transformers>=3.0.0",
    "sqlite-vec>=0.1.0",
    "pymupdf>=1.24.0",
    "click>=8.0.0",
]

[project.optional-dependencies]
azure = [
    "PyJWT>=2.8.0",
    "cryptography>=42.0.0",
]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
mskb-ingest = "ms_knowledge_base.scripts.ingest:main"
mskb-serve = "ms_knowledge_base.server.main:main"
```

**Install notes**:
- Beelink (local): `pip install .` — no azure extras needed
- Azure Container Apps: `pip install ".[azure]"` — includes JWT validation libs

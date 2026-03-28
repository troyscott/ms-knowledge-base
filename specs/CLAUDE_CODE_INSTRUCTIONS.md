# Claude Code Auto Mode — Build Instructions

## Project: ms-knowledge-base

Read ALL spec files in the `specs/` directory before writing any code. These are the contracts:
- `specs/architecture.md` — system architecture, tech stack, file structure, data governance
- `specs/ingestion-spec.md` — PDF extraction, chunking, embedding, database schema
- `specs/mcp-server-spec.md` — MCP server tools, search implementation, configuration

## Build Order

Follow this sequence strictly:

### Phase 1: Project Setup
1. Initialize the project structure per `architecture.md` file tree
2. Create `pyproject.toml` with all dependencies
3. Create `config/settings.py` with all configuration constants
4. Create `.gitignore` (include `content/`, `data/`, `*.db`, `__pycache__/`, `.venv/`)

### Phase 2: Database Layer
1. Implement `src/db/schema.py` — SQLite setup with sqlite-vec and FTS5
2. Implement `src/db/operations.py` — CRUD for sources and chunks tables
3. Write and run `tests/test_db.py`

### Phase 3: Ingestion Pipeline
1. Implement `src/ingest/pdf_reader.py` — PyMuPDF extraction per spec
2. Implement `src/ingest/chunker.py` — heading-aware chunking per spec
3. Implement `src/ingest/embedder.py` — sentence-transformers wrapper
4. Implement `src/ingest/pipeline.py` — orchestrator with incremental logic
5. Create `scripts/ingest.py` — CLI entry point
6. Write and run `tests/test_chunker.py`

### Phase 4: MCP Server
1. Implement `src/server/search.py` — KBSearchEngine class per spec
2. Implement `src/server/auth.py` — auth middleware (none, apikey, entra modes)
3. Implement `src/server/tools.py` — all four tool definitions
4. Implement `src/server/main.py` — entry point with dual transport and auth flags
5. Write and run `tests/test_search.py` and `tests/test_tools.py`

### Phase 5: Integration Test
1. Create a small test PDF in `tests/fixtures/` with known content
2. Run the full pipeline: ingest → search → verify results
3. Test both stdio and SSE transport modes
4. Test apikey auth mode (entra can be tested manually against a real tenant)

### Phase 6: Containerization
1. Create `Dockerfile` per architecture spec (bake model + DB into image)
2. Create `.dockerignore` (exclude content/, .venv/, tests/, specs/)
3. Test with `podman build` and `podman run` locally on Beelink
4. Document the ACR push + Azure Container Apps deployment in README

## Critical Constraints

- **Python 3.11+** — use modern typing (str | None, not Optional[str])
- **No GPU code** — all embedding runs on CPU, do not import torch.cuda
- **SQLite WAL mode** — set on every connection for concurrent read safety
- **Embedding model loaded ONCE** — at server/pipeline startup, not per request
- **No external API calls at query time** — everything runs local
- **Heading breadcrumb in chunk content** — prepend `# Topic > Subtopic` before chunk text for better embedding context
- **All dataclasses use slots=True** — for memory efficiency on the N100
- **Type hints on all functions** — this codebase should be fully typed

## Testing Approach

- Use pytest with small fixtures (no large PDFs in the repo)
- Mock the embedding model in unit tests (use random vectors)
- Integration tests can use the real model with a tiny test corpus
- Performance test: assert search latency < 200ms on 1000 chunks

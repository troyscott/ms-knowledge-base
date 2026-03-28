# ms-knowledge-base

Local MCP server providing semantic search over curated Microsoft technical content — Fabric, Data Engineering, AI Engineering, and Purview.

## Features

- **PDF ingestion** with heading-aware chunking and topic classification
- **Hybrid search** combining vector similarity (sqlite-vec) and keyword matching (FTS5)
- **MCP server** with stdio and SSE transports via FastMCP
- **Incremental ingestion** — unchanged files are skipped automatically
- **4 MCP tools:** `search_kb`, `list_topics`, `get_chunk_context`, `get_source_info`

## Requirements

- Python 3.11+
- ~500MB disk for torch (CPU) + sentence-transformers model

## Setup

```bash
# Install torch CPU-only (avoids large CUDA download)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install project in editable mode with dev dependencies
pip install -e ".[dev]"
```

## Usage

### Ingest content

```bash
# Single file
python scripts/ingest.py --file content/microsoft-learn/fabric-fundamentals.pdf.pdf

# Entire directory
python scripts/ingest.py --dir content/

# Force re-ingestion
python scripts/ingest.py --dir content/ --force

# View stats
python scripts/ingest.py --stats
```

### Start MCP server

```bash
# stdio transport (for Claude Desktop / Claude Code)
python -m ms_knowledge_base.server.main --transport stdio

# SSE transport (for network access)
python -m ms_knowledge_base.server.main --transport sse --port 3200

# With API key auth
python -m ms_knowledge_base.server.main --transport sse --auth apikey --auth-token YOUR_KEY
```

### Run tests

```bash
python -m pytest tests/ -v
```

## Project Structure

```
src/ms_knowledge_base/
  db/           SQLite + sqlite-vec + FTS5 schema and operations
  ingest/       PDF reader, chunker, embedder, pipeline orchestrator
  server/       MCP server, hybrid search engine, auth middleware
config/         Constants, topic keywords, search parameters
scripts/        CLI entry points
tests/          Unit, search, and integration tests
content/        Source PDFs (gitignored)
data/           Generated database (gitignored)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| PDF extraction | PyMuPDF |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2, 384-dim) |
| Vector search | SQLite + sqlite-vec |
| Keyword search | SQLite FTS5 |
| MCP framework | FastMCP |
| Auth | API key / Microsoft Entra ID (JWT) |

## Content Taxonomy

Topics span: `fabric/*`, `purview/*`, `data-engineering/*`, `ai-engineering/*`, and `patterns/*`. See `config/settings.py` for the full keyword mapping.

## Deployment

The `Dockerfile` bakes the embedding model and `knowledge.db` into the image so there are no runtime downloads or external dependencies.

### Prerequisites

- **Podman** (or Docker) installed locally
- Ingestion already run so `data/knowledge.db` exists
- For Azure: an Azure Container Registry (ACR) and Azure Container Apps resource

### Build and test locally

```bash
# Build the image (uses Podman; substitute `docker` if needed)
podman build -t ms-knowledge-base .

# Run locally — no auth, SSE on port 3200
podman run -p 3200:3200 ms-knowledge-base \
    python -m ms_knowledge_base.server.main \
    --transport sse --host 0.0.0.0 --port 3200 --auth none

# Run with API key auth
podman run -p 3200:3200 ms-knowledge-base \
    python -m ms_knowledge_base.server.main \
    --transport sse --host 0.0.0.0 --port 3200 \
    --auth apikey --auth-token "your-secret-key"
```

### Push to Azure Container Registry

```bash
# Tag for your ACR
podman tag ms-knowledge-base your-acr.azurecr.io/ms-knowledge-base:latest

# Login to ACR
podman login your-acr.azurecr.io

# Push
podman push your-acr.azurecr.io/ms-knowledge-base:latest
```

### Deploy to Azure Container Apps

After pushing to ACR, create or update a Container App that pulls from the registry. The default `CMD` in the Dockerfile starts the server with Entra ID auth:

```
python -m ms_knowledge_base.server.main --transport sse --host 0.0.0.0 --port 3200 --auth entra
```

Override `--tenant-id` and `--client-id` via environment variables or command args in the Container App configuration.

### Updating the knowledge base

Content updates follow this cycle:

1. Add/update PDFs in `content/` on the Beelink
2. Re-run ingestion: `python scripts/ingest.py --dir content/`
3. Rebuild the image: `podman build -t ms-knowledge-base .`
4. Push to ACR and redeploy the Container App

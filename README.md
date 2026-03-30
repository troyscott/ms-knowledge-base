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

## Claude Desktop

### Option A: Local (stdio)

The simplest setup — Claude Desktop launches the MCP server as a subprocess. Add this to your `claude_desktop_config.json`.

**macOS:**

Config location: `~/Library/Application Support/Claude/claude_desktop_config.json`

```jsonc
{
  "mcpServers": {
    "ms-knowledge-base": {
      "command": "python",
      "args": ["-m", "ms_knowledge_base.server.main", "--transport", "stdio"],
      "cwd": "/Users/yourname/projects/ms-knowledge-base"
    }
  }
}
```

**Windows 11:**

Config location: `%APPDATA%\Claude\claude_desktop_config.json`

```jsonc
{
  "mcpServers": {
    "ms-knowledge-base": {
      "command": "python",
      "args": ["-m", "ms_knowledge_base.server.main", "--transport", "stdio"],
      "cwd": "C:\\Users\\YourName\\projects\\ms-knowledge-base"
    }
  }
}
```

Adjust `cwd` to match your install path. The server loads the embedding model on startup (~5-10s), then Claude Desktop can call `search_kb`, `list_topics`, `get_chunk_context`, and `get_source_info`.

### Option B: Remote via Tailscale (SSE)

Access the MCP server from Claude Desktop on a different machine over your Tailscale network. Two approaches:

**Tailscale Serve** (tailnet-only, private to your Tailscale network):

```bash
# On the host machine — start the MCP server
python -m ms_knowledge_base.server.main --transport sse --host 0.0.0.0 --port 3200

# Expose port 3200 via Tailscale Serve (accessible only within your tailnet)
tailscale serve --bg 3200
```

**Tailscale Funnel** (publicly reachable over HTTPS — use with API key auth):

```bash
# On the host machine — start the MCP server with auth
python -m ms_knowledge_base.server.main --transport sse --host 0.0.0.0 --port 3200 \
    --auth apikey --auth-token YOUR_SECRET_KEY

# Expose port 3200 via Tailscale Funnel (publicly reachable)
tailscale funnel 3200
```

Then configure Claude Desktop on the remote machine to connect via `mcp-remote` with the auth header:

```jsonc
{
  "mcpServers": {
    "ms-knowledge-base": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://lotus.boga-vernier.ts.net/sse",
        "--header", "Authorization:Bearer ${MCP_API_KEY}"
      ],
      "env": {
        "MCP_API_KEY": "YOUR_SECRET_KEY"
      }
    }
  }
}
```

Replace `lotus.boga-vernier.ts.net` with your machine's Tailscale hostname and `YOUR_SECRET_KEY` with your chosen API key.

> **Note:** Tailscale Serve keeps traffic within your tailnet (private). Tailscale Funnel makes the endpoint reachable from the public internet over HTTPS. Always use `--auth apikey` when exposing via Funnel.

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

## Troubleshooting

### Claude Desktop: "VM service not running"

If Claude Desktop shows **"VM service not running. The service failed to start"**, the Claude Windows service hasn't started. Fix it from an admin command prompt:

```
net start Claude
```

Then relaunch Claude Desktop. This can happen after a reboot or terminal crash.

### Micromamba: "Shell not initialized"

If `micromamba activate podman` fails with **"Shell not initialized"**, run:

```
micromamba shell init --shell cmd.exe --root-prefix="C:\Users\Troy Scott\micromamba"
```

Then close and reopen your command prompt. The root prefix must point to where your envs actually live (`C:\Users\Troy Scott\micromamba`), not the default `%USERPROFILE%\.local\share\mamba`.

## Content Taxonomy

Topics span: `fabric/*`, `purview/*`, `data-engineering/*`, `ai-engineering/*`, and `patterns/*`. See `config/settings.py` for the full keyword mapping.

## Deployment (Podman / Docker)

The image bakes in the embedding model and code but **not** the database or content. Data lives on named volumes so it persists across container rebuilds, bug fixes, and feature updates.

### 1. Build the image

```bash
podman build -t ms-knowledge-base .
```

### 2. Create named volumes

```bash
podman volume create mskb-data     # knowledge.db lives here
podman volume create mskb-content  # source PDFs live here
```

### 3. Add content to the volume

Copy PDFs into the content volume from your host:

```bash
# Copy a single file
podman run --rm -v mskb-content:/app/content \
    -v "/c/Users/Troy Scott/projects/ms-knowledge-base/content":/src:ro \
    busybox cp -r /src/. /app/content/

# Or bind-mount your host content directory directly (simpler for local dev)
# See the ingestion step below
```

### 4. Run ingestion

Ingest PDFs into the knowledge base. This writes `knowledge.db` into the data volume:

```bash
podman run --rm \
    -v mskb-data:/app/data \
    -v mskb-content:/app/content \
    ms-knowledge-base \
    python scripts/ingest.py --dir /app/content
```

Or bind-mount your host directories directly:

```bash
podman run --rm \
    -v mskb-data:/app/data \
    -v "/c/Users/Troy Scott/projects/ms-knowledge-base/content":/app/content:ro \
    ms-knowledge-base \
    python scripts/ingest.py --dir /app/content
```

Check stats:

```bash
podman run --rm -v mskb-data:/app/data ms-knowledge-base \
    python scripts/ingest.py --stats
```

### 5. Run the server

```bash
# No auth (local dev)
podman run -d --name mskb \
    -p 3200:3200 \
    -v mskb-data:/app/data:ro \
    ms-knowledge-base

# With API key auth
podman run -d --name mskb \
    -p 3200:3200 \
    -v mskb-data:/app/data:ro \
    ms-knowledge-base \
    python -m ms_knowledge_base.server.main \
    --transport sse --host 0.0.0.0 --port 3200 \
    --auth apikey --auth-token "your-secret-key"
```

### Updating the knowledge base

No rebuild needed — just re-run ingestion against the same volumes:

1. Add new PDFs to `mskb-content` (or bind-mount from host)
2. Run the ingestion container (step 4 above) — unchanged files are skipped automatically
3. Restart the server container: `podman restart mskb`

### Rebuilding after code changes

```bash
podman build -t ms-knowledge-base .
podman stop mskb && podman rm mskb
# Re-run server (step 5) — data volume is untouched
```

### Azure Container Apps

For Azure deployment, bake the database into a production image so the container is self-contained:

```bash
# Build a production image with DB included
podman run --rm -v mskb-data:/app/data ms-knowledge-base \
    cat /app/data/knowledge.db > knowledge-export.db

# Use a Dockerfile.prod that COPYs knowledge-export.db into the image
podman build -f Dockerfile.prod -t ms-knowledge-base:prod .

# Push to ACR
podman tag ms-knowledge-base:prod your-acr.azurecr.io/ms-knowledge-base:latest
podman login your-acr.azurecr.io
podman push your-acr.azurecr.io/ms-knowledge-base:latest
```

Override auth settings in the Container App configuration:

```
python -m ms_knowledge_base.server.main --transport sse --host 0.0.0.0 --port 3200 --auth entra --tenant-id YOUR_TENANT --client-id YOUR_CLIENT
```

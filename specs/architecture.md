# Microsoft Knowledge Base — Architecture Specification

## Project Identity

- **Name**: ms-knowledge-base
- **Purpose**: Local MCP server providing semantic search over curated Microsoft technical content (Fabric, Data Engineering, AI Engineering)
- **Host**: Beelink mini PC (Intel N100, 16GB RAM, Windows 11, Tailscale hostname: `tulip`)
- **Language**: Python (single language for server, ingestion, and embedding)
- **Transport**: Dual — stdio (Claude Desktop local) + SSE (remote via Tailscale)
- **Data Policy**: NO customer data, NO proprietary project references. Microsoft public docs, official sample data, and personal study notes only.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Content Sources                        │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ MS Learn PDFs│  │ FabCon Notes │  │ Personal Notes│  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼─────────────────┼──────────────────┼──────────┘
          └─────────────────┼──────────────────┘
                            ▼
                ┌───────────────────────┐
                │   Ingestion Pipeline  │
                │  PDF → Chunks → Embed │
                │  (PyMuPDF + sentence- │
                │   transformers)       │
                └───────────┬───────────┘
                            ▼
                ┌───────────────────────┐
                │   SQLite + sqlite-vec │
                │   knowledge.db        │
                │  ┌─────────────────┐  │
                │  │ chunks table    │  │
                │  │ - id            │  │
                │  │ - content       │  │
                │  │ - embedding     │  │
                │  │ - source_file   │  │
                │  │ - source_type   │  │
                │  │ - topic         │  │
                │  │ - section_title │  │
                │  │ - chunk_index   │  │
                │  │ - page_number   │  │
                │  └─────────────────┘  │
                └───────────┬───────────┘
                            ▼
                ┌───────────────────────┐
                │     MCP Server        │
                │  (Python, FastMCP)    │
                │                       │
                │  Tools:               │
                │  - search_kb          │
                │  - list_topics        │
                │  - get_chunk_context  │
                │  - get_source_info    │
                │                       │
                │  Transport:           │
                │  - stdio (local)      │
                │  - SSE (Tailscale)    │
                └───────────┬───────────┘
                    ┌───────┴───────┐
                    ▼               ▼
          ┌──────────────┐  ┌──────────────┐
          │Claude Desktop│  │Remote Clients│
          │  (stdio)     │  │  (SSE/HTTP)  │
          │  local       │  │  Tailscale   │
          └──────────────┘  └──────────────┘
```

---

## Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| MCP Framework | `fastmcp` (Python) | Native Python MCP SDK, supports stdio + SSE |
| Vector Storage | SQLite + `sqlite-vec` | Zero-service, single file, minimal RAM, fast on CPU |
| Embedding Model | `all-MiniLM-L6-v2` via `sentence-transformers` | ~80MB, CPU-friendly, 384-dim vectors, good semantic quality |
| PDF Extraction | `PyMuPDF` (fitz) | Fast, reliable, preserves structure and page numbers |
| Chunking | Custom (heading-aware) | Split by headings/sections, not arbitrary token windows |
| Container | Podman (optional) | For isolation if desired; can also run bare Python |

---

## Compute Budget (N100 Constraints)

The N100 has 4 cores, no GPU. Every design decision optimizes for this:

- **Embeddings are pre-computed at ingestion time** — no embedding at query time except the single query string
- **Single query embedding**: ~50ms on CPU (384-dim, MiniLM)
- **SQLite-vec similarity search**: ~5-10ms for 10k chunks
- **Total per-request latency target**: < 200ms
- **Memory footprint**: Embedding model loads once at server start (~300MB), stays resident
- **No GPU required**: sentence-transformers on CPU is sufficient for single-query workloads

---

## Content Taxonomy

### Topics (used for filtering and metadata)

```
fabric/lakehouse
fabric/warehouse
fabric/pipelines
fabric/notebooks
fabric/real-time-hub
fabric/activator
fabric/iq
fabric/iq/ontology
fabric/iq/data-agents
fabric/iq/mcp
fabric/monitoring
purview/governance
purview/lineage
purview/data-catalog
purview/sensitivity-labels
data-engineering/medallion
data-engineering/cdc
data-engineering/delta-tables
data-engineering/spark
ai-engineering/foundry
ai-engineering/ai-skills
ai-engineering/agents
ai-engineering/prompt-flow
patterns/ontology-design
patterns/confidence-waterfall
patterns/event-driven
```

### Source Types

```
microsoft_official    — Microsoft Learn docs, official documentation
microsoft_sample     — AdventureWorksLT, WWI, Fabric sample datasets
fabcon_notes         — FabCon session notes and recordings transcripts
personal_notes       — Personal study notes (no customer references)
```

---

## File Structure

```
ms-knowledge-base/
├── specs/
│   ├── architecture.md          ← this file
│   ├── ingestion-spec.md        ← ingestion pipeline spec
│   ├── mcp-server-spec.md       ← MCP server spec
│   └── CLAUDE_CODE_INSTRUCTIONS.md ← build instructions for auto mode
├── src/
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── pdf_reader.py        ← PDF extraction with PyMuPDF
│   │   ├── chunker.py           ← heading-aware chunking
│   │   ├── embedder.py          ← sentence-transformers wrapper
│   │   └── pipeline.py          ← orchestrates ingest flow
│   ├── server/
│   │   ├── __init__.py
│   │   ├── main.py              ← MCP server entry point
│   │   ├── tools.py             ← tool definitions
│   │   ├── search.py            ← query embedding + similarity search
│   │   └── auth.py              ← auth middleware (none/apikey/entra)
│   └── db/
│       ├── __init__.py
│       ├── schema.py            ← SQLite + sqlite-vec setup
│       └── operations.py        ← CRUD operations
├── content/                     ← source PDFs (gitignored)
│   ├── microsoft-learn/
│   ├── fabcon/
│   ├── sample-data/             ← MS sample dataset descriptions
│   └── notes/
├── data/
│   └── knowledge.db             ← SQLite database (gitignored)
├── config/
│   └── settings.py              ← configuration (paths, model name, chunk sizes)
├── scripts/
│   ├── ingest.py                ← CLI entry point for ingestion
│   └── serve.py                 ← CLI entry point for server
├── tests/
│   ├── fixtures/                ← small test PDFs
│   ├── test_chunker.py
│   ├── test_search.py
│   └── test_tools.py
├── Dockerfile                   ← for Azure Container Apps deployment
├── .dockerignore
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## Deployment Model

This server has two deployment targets serving different access patterns:

### Deployment A: Beelink (Local / Tailscale)

- **Purpose**: Development, personal use, Claude Desktop integration
- **Host**: Beelink mini PC (tulip.boga-vernier.ts.net)
- **Transports**: stdio (Claude Desktop local), SSE (Tailscale for personal remote access)
- **Auth**: None needed — Tailscale ACLs handle network-level access
- **Use case**: Day-to-day querying from Claude Desktop, content ingestion, testing

### Deployment B: Azure Container Apps (Fabric / Enterprise)

- **Purpose**: Access from Microsoft Fabric notebooks, Copilot 365, enterprise integrations
- **Host**: Azure Container Apps (serverless, scales to zero when idle)
- **Transport**: SSE (HTTPS)
- **Auth**: Microsoft Entra ID (Azure AD) — managed identity + token validation
- **Use case**: Fabric notebooks querying the KB during development, Copilot plugin (future)

```
┌─────────────────────────────────────┐
│          Beelink (tulip)            │
│  ┌─────────────┐  ┌─────────────┐  │
│  │ MCP Server  │  │ Ingestion   │  │
│  │ stdio + SSE │  │ Pipeline    │  │
│  └──────┬──────┘  └──────┬──────┘  │
│         │                │          │
│         │         ┌──────┴──────┐   │
│         │         │ knowledge.db│   │
│         │         └──────┬──────┘   │
│         │                │          │
│  ┌──────┴────────────────┴──────┐   │
│  │        Tailscale             │   │
│  └──────────────────────────────┘   │
└──────────┬──────────────────────────┘
           │
           ▼ (personal / dev access)
    Claude Desktop
    Other Tailscale nodes


┌─────────────────────────────────────┐
│    Azure Container Apps             │
│  ┌─────────────┐  ┌─────────────┐  │
│  │ MCP Server  │  │ knowledge.db│  │
│  │ SSE (HTTPS) │  │ (bundled)   │  │
│  └──────┬──────┘  └─────────────┘  │
│         │                           │
│  ┌──────┴──────────────────────┐    │
│  │  Entra ID Token Validation  │    │
│  └──────┬──────────────────────┘    │
└─────────┼───────────────────────────┘
          │
          ▼ (enterprise access)
   Fabric Notebooks
   Copilot 365 (future)
```

### DB Sync Strategy

Ingestion runs on the Beelink (where your PDFs live). The Azure deployment receives
a copy of `knowledge.db` — it is read-only and does not run ingestion.

Sync options (pick one during implementation):
1. **Azure Blob Storage**: After ingestion, upload `knowledge.db` to a blob container.
   Azure Container App mounts the blob or downloads on startup.
2. **Container image rebuild**: Include `knowledge.db` in the Docker image. Rebuild
   and redeploy after re-ingestion. Simplest if content updates are infrequent.
3. **Azure File Share**: Mount a shared file system between ingestion and the container.

Option 2 is recommended to start — content updates will be periodic (weekly at most),
and baking the DB into the image means zero runtime dependencies.

---

## Security and Data Governance

### Data Policy
1. **No customer data**: Ingestion pipeline rejects files from paths containing project-specific identifiers
2. **Source provenance**: Every chunk tagged with `source_type` — queries can filter by source
3. **No outbound API calls at query time**: Embedding model is local/bundled, no data leaves the host

### Beelink Security
- Tailscale ACLs control network access — SSE endpoint binds to Tailscale interface only
- No authentication layer needed (Tailscale provides identity-based access)

### Azure Security
- **Entra ID authentication**: All requests to the Azure-hosted MCP server require a valid
  Entra ID token. The server validates the token's audience, issuer, and tenant.
- **Managed Identity**: Fabric notebooks authenticate using their workspace's managed identity —
  no secrets stored in notebook code.
- **Virtual Network**: Azure Container Apps deployed within a VNet if additional isolation needed.
- **No public endpoint without auth**: The Container App's ingress requires authentication;
  unauthenticated requests are rejected at the platform level.

### Auth Implementation

The MCP server supports an `--auth` flag with three modes:

```bash
# No auth (Beelink local / Tailscale)
python -m ms_knowledge_base.server.main --transport stdio
python -m ms_knowledge_base.server.main --transport sse --auth none

# API key (simple, for testing)
python -m ms_knowledge_base.server.main --transport sse --auth apikey --auth-token "your-secret"

# Entra ID (Azure deployment)
python -m ms_knowledge_base.server.main --transport sse --auth entra \
    --tenant-id "your-tenant-id" \
    --client-id "your-app-registration-client-id"
```

**Entra ID token validation** (in `src/server/auth.py`):
```python
# Validates JWT from Authorization: Bearer <token> header
# Checks: signature (via JWKS), audience (client_id), issuer (tenant), expiry
# Uses: PyJWT + cryptography libraries
# Caches JWKS keys to avoid per-request fetch
```

**Fabric notebook calling pattern**:
```python
# In a Fabric notebook — uses workspace managed identity
from azure.identity import ManagedIdentityCredential

credential = ManagedIdentityCredential()
token = credential.get_token("api://your-app-registration-client-id/.default")

import requests
response = requests.post(
    "https://ms-kb.your-container-app.azurecontainerapps.io/messages",
    headers={"Authorization": f"Bearer {token.token}"},
    json={
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "search_kb",
            "arguments": {"query": "Fabric IQ ontology authoring"}
        },
        "id": 1
    }
)
```

---

## Integration Points

### Claude Desktop — Local (stdio)

```jsonc
// claude_desktop_config.json
{
  "mcpServers": {
    "ms-knowledge-base": {
      "command": "python",
      "args": ["-m", "ms_knowledge_base.server.main", "--transport", "stdio"],
      "cwd": "C:\\path\\to\\ms-knowledge-base"
    }
  }
}
```

### Claude Desktop — Remote via Tailscale (SSE)

```bash
# Server start on Beelink
python -m ms_knowledge_base.server.main --transport sse --host tulip.boga-vernier.ts.net --port 3200

# Claude Desktop remote config (via mcp-remote)
{
  "mcpServers": {
    "ms-knowledge-base": {
      "command": "npx",
      "args": ["mcp-remote", "http://tulip.boga-vernier.ts.net:3200/sse"]
    }
  }
}
```

### Microsoft Fabric Notebooks

```python
# Authenticate via managed identity, call Azure-hosted MCP server
# See Auth Implementation section above for full pattern
```

### Copilot 365 (future)

Copilot 365 integration via Copilot Studio plugin pointing at the Azure Container Apps
endpoint. The Entra ID auth model is already compatible — Copilot authenticates with the
same tenant. This becomes a configuration task, not a code change.

---

## Containerization (for Azure deployment)

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY config/ config/
COPY data/knowledge.db data/knowledge.db

# Pre-download embedding model at build time (not at runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 3200

CMD ["python", "-m", "ms_knowledge_base.server.main", \
     "--transport", "sse", \
     "--host", "0.0.0.0", \
     "--port", "3200", \
     "--auth", "entra"]
```

**Build and deploy flow**:
```bash
# On the Beelink after ingestion
podman build -t ms-knowledge-base .
podman tag ms-knowledge-base your-acr.azurecr.io/ms-knowledge-base:latest
podman push your-acr.azurecr.io/ms-knowledge-base:latest

# Azure Container Apps pulls from ACR and deploys
```

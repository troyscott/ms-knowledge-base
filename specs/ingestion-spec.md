# Microsoft Knowledge Base — Ingestion Pipeline Specification

## Purpose

Transform PDF documents and text notes into chunked, embedded, searchable content stored in SQLite with vector indexing. This pipeline runs offline (not at query time) and can be re-run incrementally as new content is added.

---

## Pipeline Flow

```
Input PDF/Text
     │
     ▼
┌─────────────┐
│  Extract     │  PyMuPDF for PDFs, plain read for .md/.txt
│  Raw Text    │  Preserve page numbers, heading structure
└──────┬──────┘
       ▼
┌─────────────┐
│  Chunk       │  Split by headings/sections
│  Content     │  Target: 300-500 tokens per chunk
│              │  Overlap: 50 tokens between chunks
└──────┬──────┘
       ▼
┌─────────────┐
│  Classify    │  Auto-tag topic from taxonomy
│  Metadata    │  Set source_type from directory path
└──────┬──────┘
       ▼
┌─────────────┐
│  Embed       │  all-MiniLM-L6-v2 (384 dimensions)
│  Chunks      │  Batch embed for efficiency
└──────┬──────┘
       ▼
┌─────────────┐
│  Store       │  SQLite + sqlite-vec
│  in DB       │  Upsert (skip unchanged content)
└─────────────┘
```

---

## Component Specifications

### 1. PDF Reader (`src/ingest/pdf_reader.py`)

**Library**: PyMuPDF (`fitz`)

**Responsibilities**:
- Extract text from PDF preserving page boundaries
- Detect and preserve heading hierarchy (using font size heuristics)
- Return structured output: list of `PageContent` objects

**Interface**:
```python
@dataclass
class HeadingBlock:
    level: int          # 1=H1, 2=H2, 3=H3
    text: str
    page_number: int

@dataclass
class TextBlock:
    text: str
    page_number: int
    heading_context: list[str]  # breadcrumb of parent headings

@dataclass
class PageContent:
    page_number: int
    blocks: list[HeadingBlock | TextBlock]

def extract_pdf(file_path: Path) -> list[PageContent]:
    """Extract structured content from a PDF file."""
    ...
```

**Heading Detection Heuristic**:
- Track font sizes across the document
- The most common font size = body text
- Fonts significantly larger than body = headings
- Classify into 3 levels based on relative size
- Bold text at body size with its own line = potential H3

**Edge Cases**:
- Multi-column layouts: process columns left-to-right
- Headers/footers: detect repeated text at top/bottom of pages, exclude
- Tables: extract as plain text with column separation
- Images: skip (no OCR needed for Microsoft Learn docs)

---

### 2. Chunker (`src/ingest/chunker.py`)

**Strategy**: Heading-aware semantic chunking

**Responsibilities**:
- Split extracted text into chunks that respect heading boundaries
- Maintain heading context (breadcrumb) for each chunk
- Target chunk size: 300-500 tokens (approximately 1200-2000 characters)
- Overlap: 50 tokens (~200 characters) between consecutive chunks within the same section
- Never split mid-sentence

**Interface**:
```python
@dataclass
class Chunk:
    content: str
    section_title: str          # immediate heading
    heading_breadcrumb: list[str]  # full heading path
    page_number: int            # starting page
    chunk_index: int            # position within source file
    char_count: int
    token_estimate: int         # chars / 4 approximation

def chunk_content(
    pages: list[PageContent],
    target_tokens: int = 400,
    max_tokens: int = 500,
    overlap_tokens: int = 50
) -> list[Chunk]:
    """Split page content into semantic chunks."""
    ...
```

**Chunking Rules**:
1. A new heading always starts a new chunk
2. If a section is shorter than `target_tokens`, keep it as one chunk
3. If a section exceeds `max_tokens`, split at sentence boundaries
4. Overlap includes the last N tokens of the previous chunk prepended to the next
5. Each chunk's `content` is prefixed with its heading breadcrumb for embedding context:
   ```
   # Fabric > Lakehouse > Delta Tables
   
   Delta tables in Microsoft Fabric lakehouse support...
   ```
   This ensures the embedding captures topic context even for generic text.

---

### 3. Embedder (`src/ingest/embedder.py`)

**Model**: `sentence-transformers/all-MiniLM-L6-v2`
- Dimensions: 384
- Size: ~80MB
- Performance: ~50ms per embedding on CPU, supports batch encoding

**Interface**:
```python
class Embedder:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """Load the sentence-transformers model."""
        ...
    
    def embed_text(self, text: str) -> list[float]:
        """Embed a single text string. Used for queries."""
        ...
    
    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Embed multiple texts efficiently. Used for ingestion."""
        ...
```

**Optimization**:
- Batch encoding during ingestion (batch_size=32)
- Model loaded once at pipeline start, reused across all files
- Normalize embeddings to unit vectors for cosine similarity (MiniLM default)

---

### 4. Topic Classifier

**Approach**: Rule-based keyword matching (no ML needed)

Topics are assigned based on:
1. **Directory path** → source_type (microsoft-learn/ → microsoft_official, etc.)
2. **Heading content** → topic from taxonomy
3. **Keyword matching** → fallback topic assignment

```python
TOPIC_KEYWORDS = {
    "fabric/lakehouse": ["lakehouse", "delta lake", "delta table", "spark pool"],
    "fabric/iq": ["fabric iq", "data agent", "ontology"],
    "fabric/iq/ontology": ["ontology authoring", "semantic model", "business concept"],
    "purview/governance": ["purview", "governance", "classification", "sensitivity"],
    "purview/lineage": ["lineage", "data lineage", "impact analysis"],
    # ... full taxonomy
}

def classify_topic(chunk: Chunk, file_path: Path) -> str:
    """Assign the most specific matching topic from taxonomy."""
    ...
```

A chunk can have multiple topic tags. The classifier returns the most specific match.

---

### 5. Pipeline Orchestrator (`src/ingest/pipeline.py`)

**Interface**:
```python
def ingest_file(
    file_path: Path,
    db_path: Path,
    source_type: str | None = None,
    force: bool = False
) -> IngestResult:
    """Ingest a single file into the knowledge base."""
    ...

def ingest_directory(
    dir_path: Path,
    db_path: Path,
    source_type: str | None = None,
    force: bool = False
) -> list[IngestResult]:
    """Ingest all supported files in a directory."""
    ...

@dataclass
class IngestResult:
    file_path: Path
    chunks_created: int
    chunks_skipped: int  # already existed, unchanged
    source_type: str
    topics_found: list[str]
    errors: list[str]
```

**Incremental Ingestion**:
- Hash each source file (SHA-256)
- Store hash in a `sources` table
- On re-run, skip files whose hash hasn't changed (unless `force=True`)
- If a file has changed, delete its old chunks and re-ingest

---

### 6. CLI Entry Point (`scripts/ingest.py`)

```bash
# Ingest a single PDF
python scripts/ingest.py --file content/microsoft-learn/fabric-lakehouse.pdf

# Ingest an entire directory
python scripts/ingest.py --dir content/microsoft-learn/

# Force re-ingestion
python scripts/ingest.py --dir content/ --force

# Show stats
python scripts/ingest.py --stats
```

---

## Database Schema

```sql
-- Source file tracking for incremental ingestion
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_hash TEXT NOT NULL,
    source_type TEXT NOT NULL,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    chunk_count INTEGER DEFAULT 0
);

-- Content chunks with metadata
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    section_title TEXT,
    heading_breadcrumb TEXT,       -- JSON array of heading path
    topic TEXT NOT NULL,            -- primary topic from taxonomy
    topic_tags TEXT,                -- JSON array of all matching topics
    page_number INTEGER,
    chunk_index INTEGER NOT NULL,
    token_estimate INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vector index (sqlite-vec virtual table)
CREATE VIRTUAL TABLE chunk_embeddings USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);

-- Full-text search fallback
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    section_title,
    topic,
    content='chunks',
    content_rowid='id'
);

-- Indexes
CREATE INDEX idx_chunks_topic ON chunks(topic);
CREATE INDEX idx_chunks_source ON chunks(source_id);
```

**Notes**:
- `sqlite-vec` provides the vector similarity search
- `fts5` provides keyword fallback for exact term matching
- Both are SQLite built-in/extension — no additional services
- The `chunks_fts` table is a content-sync FTS table tied to the `chunks` table

---

## Microsoft Sample Data to Include

These should be documented as reference entries in the KB, not as raw data files:

| Sample Dataset | Use Case | Topic |
|---------------|----------|-------|
| AdventureWorksLT | SQL sample database, relational patterns | data-engineering/medallion |
| Wide World Importers | Data warehouse patterns, fact/dimension | fabric/warehouse |
| Fabric Sample Lakehouse | Built-in lakehouse demo data | fabric/lakehouse |
| Fabric Sample Warehouse | Built-in warehouse demo data | fabric/warehouse |
| Fabric IQ Sample Ontology | Ontology authoring examples from FabCon | fabric/iq/ontology |

For each, create a markdown document in `content/sample-data/` describing the schema, intended use cases, and how they map to Fabric patterns. These get ingested alongside the PDF content.

---

## Error Handling

- **Corrupt PDF**: Log error, skip file, continue with remaining files
- **Empty chunks**: Skip chunks with fewer than 50 characters after stripping whitespace
- **Embedding failure**: Retry once, then skip chunk with warning
- **Database lock**: Use WAL mode for SQLite to allow concurrent reads during ingestion
- **Disk space**: Check available space before starting batch ingestion

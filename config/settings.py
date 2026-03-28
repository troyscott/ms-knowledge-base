from pathlib import Path

# Project root (two levels up from config/settings.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Paths
DB_PATH = PROJECT_ROOT / "data" / "knowledge.db"
CONTENT_DIR = PROJECT_ROOT / "content"

# Embedding
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# Chunking
CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
CHUNK_MIN_CHARS = 50

# Search
DEFAULT_MAX_RESULTS = 5
VECTOR_WEIGHT = 0.7
FTS_WEIGHT = 0.3
CANDIDATE_MULTIPLIER = 2

# Server
SSE_DEFAULT_PORT = 3200
SSE_DEFAULT_HOST = "0.0.0.0"

# Source type mapping (directory name -> source_type)
SOURCE_TYPE_MAP: dict[str, str] = {
    "microsoft-learn": "microsoft_official",
    "sample-data": "microsoft_sample",
    "fabcon": "fabcon_notes",
    "notes": "personal_notes",
}

# Topic keyword mapping for classification
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "fabric/lakehouse": ["lakehouse", "delta lake", "delta table", "spark pool"],
    "fabric/warehouse": ["warehouse", "synapse warehouse", "t-sql", "stored procedure"],
    "fabric/pipelines": ["pipeline", "data pipeline", "data factory", "orchestration"],
    "fabric/notebooks": ["notebook", "spark notebook", "pyspark"],
    "fabric/real-time-hub": ["real-time hub", "real-time intelligence", "eventstream"],
    "fabric/activator": ["activator", "reflex", "data activator"],
    "fabric/iq": ["fabric iq", "data agent", "ontology"],
    "fabric/iq/ontology": ["ontology authoring", "semantic model", "business concept"],
    "fabric/iq/data-agents": ["data agent", "agent authoring"],
    "fabric/iq/mcp": ["mcp", "model context protocol"],
    "fabric/monitoring": ["monitoring", "capacity metrics", "workspace monitoring"],
    "purview/governance": ["purview", "governance", "classification", "sensitivity"],
    "purview/lineage": ["lineage", "data lineage", "impact analysis"],
    "purview/data-catalog": ["data catalog", "catalog", "data discovery"],
    "purview/sensitivity-labels": ["sensitivity label", "information protection"],
    "data-engineering/medallion": ["medallion", "bronze", "silver", "gold", "lakehouse architecture"],
    "data-engineering/cdc": ["change data capture", "cdc", "incremental load"],
    "data-engineering/delta-tables": ["delta table", "delta format", "time travel", "vacuum"],
    "data-engineering/spark": ["apache spark", "spark sql", "spark streaming", "pyspark"],
    "ai-engineering/foundry": ["ai foundry", "azure ai foundry", "model deployment"],
    "ai-engineering/ai-skills": ["ai skill", "fabric ai skill"],
    "ai-engineering/agents": ["ai agent", "copilot agent", "agent framework"],
    "ai-engineering/prompt-flow": ["prompt flow", "flow authoring"],
    "patterns/ontology-design": ["ontology design", "concept mapping", "knowledge graph"],
    "patterns/confidence-waterfall": ["confidence waterfall", "confidence score"],
    "patterns/event-driven": ["event-driven", "event processing", "pub/sub"],
}

# Content taxonomy - all valid topics
VALID_TOPICS: list[str] = sorted(TOPIC_KEYWORDS.keys())

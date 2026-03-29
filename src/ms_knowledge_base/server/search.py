"""KBSearchEngine — hybrid vector + keyword search."""

import logging
import struct
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from ms_knowledge_base.ingest.embedder import Embedder

logger = logging.getLogger(__name__)

# Import settings
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "config"))
from settings import CANDIDATE_MULTIPLIER, FTS_WEIGHT, VECTOR_WEIGHT


@dataclass(slots=True)
class SearchResult:
    content: str
    section_title: str
    topic: str
    source_file: str
    source_type: str
    page_number: int | None
    relevance_score: float


@dataclass(slots=True)
class ContextChunk:
    content: str
    section_title: str
    chunk_index: int
    page_number: int | None
    is_target: bool


@dataclass(slots=True)
class TopicInfo:
    topic: str
    chunk_count: int
    source_count: int


@dataclass(slots=True)
class SourceInfo:
    file_name: str
    source_type: str
    chunk_count: int
    topics: list[str]
    ingested_at: str


class KBSearchEngine:
    """Hybrid search engine combining vector similarity and keyword matching."""

    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        self.db_path = db_path
        self.embedder = embedder

    def _get_db(self) -> sqlite3.Connection:
        """Create a thread-local database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn

    def close(self) -> None:
        pass  # connections are created and closed per-call

    def search(
        self,
        query: str,
        topic_filter: str | None = None,
        source_type: str | None = None,
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Hybrid search: vector KNN + FTS keyword boost."""
        if not query.strip():
            return []

        # Clamp max_results
        max_results = max(1, min(10, max_results))

        # 1. Embed the query
        query_embedding = self.embedder.embed_text(query)
        query_blob = struct.pack(f"{len(query_embedding)}f", *query_embedding)

        # 2. Vector KNN search
        candidate_limit = max_results * CANDIDATE_MULTIPLIER
        db = self._get_db()
        vector_rows = db.execute(
            """SELECT chunk_id, distance
               FROM chunk_embeddings
               WHERE embedding MATCH ?
               ORDER BY distance
               LIMIT ?""",
            (query_blob, candidate_limit),
        ).fetchall()

        if not vector_rows:
            return []

        # Build candidate map: chunk_id -> distance
        candidates: dict[int, float] = {
            row["chunk_id"]: row["distance"] for row in vector_rows
        }

        # 3. FTS keyword boost
        fts_ids: set[int] = set()
        try:
            fts_rows = db.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ?",
                (query,),
            ).fetchall()
            fts_ids = {row["rowid"] for row in fts_rows}
        except sqlite3.OperationalError:
            # FTS match can fail on certain query strings
            logger.debug("FTS match failed for query: %s", query)

        # 4. Fetch chunk metadata and compute final scores
        chunk_ids = list(candidates.keys())
        placeholders = ",".join("?" * len(chunk_ids))
        rows = db.execute(
            f"""SELECT c.id, c.content, c.section_title, c.topic,
                       c.page_number, c.chunk_index, c.source_id,
                       s.file_path, s.source_type
                FROM chunks c
                JOIN sources s ON c.source_id = s.id
                WHERE c.id IN ({placeholders})""",
            chunk_ids,
        ).fetchall()

        results: list[SearchResult] = []
        for row in rows:
            chunk_id = row["id"]
            distance = candidates[chunk_id]
            # Convert distance to similarity score (0-1)
            vector_score = max(0.0, 1.0 - distance)
            fts_boost = 1.0 if chunk_id in fts_ids else 0.0
            final_score = VECTOR_WEIGHT * vector_score + FTS_WEIGHT * fts_boost

            # Extract just the filename from the full path
            file_name = Path(row["file_path"]).name

            results.append(SearchResult(
                content=row["content"],
                section_title=row["section_title"] or "",
                topic=row["topic"],
                source_file=file_name,
                source_type=row["source_type"],
                page_number=row["page_number"],
                relevance_score=round(final_score, 4),
            ))

        # 5. Apply filters
        if topic_filter:
            results = [r for r in results if r.topic.startswith(topic_filter)]
        if source_type:
            results = [r for r in results if r.source_type == source_type]

        # 6. Sort by score and deduplicate
        results.sort(key=lambda r: r.relevance_score, reverse=True)
        results = self._deduplicate_adjacent(results)

        return results[:max_results]

    def get_chunk_context(
        self, source_file: str, chunk_index: int, window: int = 2
    ) -> list[ContextChunk]:
        """Get surrounding chunks for expanded context."""
        db = self._get_db()
        rows = db.execute(
            """SELECT c.content, c.section_title, c.chunk_index, c.page_number
               FROM chunks c
               JOIN sources s ON c.source_id = s.id
               WHERE s.file_path LIKE ?
                 AND c.chunk_index BETWEEN ? AND ?
               ORDER BY c.chunk_index""",
            (f"%{source_file}", chunk_index - window, chunk_index + window),
        ).fetchall()

        return [
            ContextChunk(
                content=row["content"],
                section_title=row["section_title"] or "",
                chunk_index=row["chunk_index"],
                page_number=row["page_number"],
                is_target=row["chunk_index"] == chunk_index,
            )
            for row in rows
        ]

    def list_topics(self) -> list[TopicInfo]:
        """List all topics with chunk counts."""
        db = self._get_db()
        rows = db.execute(
            """SELECT topic,
                      COUNT(*) as chunk_count,
                      COUNT(DISTINCT source_id) as source_count
               FROM chunks
               GROUP BY topic
               ORDER BY topic"""
        ).fetchall()

        return [
            TopicInfo(
                topic=row["topic"],
                chunk_count=row["chunk_count"],
                source_count=row["source_count"],
            )
            for row in rows
        ]

    def get_source_info(self, source_type: str | None = None) -> list[SourceInfo]:
        """List ingested source documents."""
        db = self._get_db()
        if source_type:
            rows = db.execute(
                "SELECT * FROM sources WHERE source_type = ? ORDER BY ingested_at DESC",
                (source_type,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM sources ORDER BY ingested_at DESC"
            ).fetchall()

        results: list[SourceInfo] = []
        for row in rows:
            topics_rows = db.execute(
                "SELECT DISTINCT topic FROM chunks WHERE source_id = ? ORDER BY topic",
                (row["id"],),
            ).fetchall()
            results.append(SourceInfo(
                file_name=Path(row["file_path"]).name,
                source_type=row["source_type"],
                chunk_count=row["chunk_count"],
                topics=[t["topic"] for t in topics_rows],
                ingested_at=row["ingested_at"],
            ))
        return results

    def _deduplicate_adjacent(self, results: list[SearchResult]) -> list[SearchResult]:
        """Merge consecutive chunks from the same source."""
        if len(results) <= 1:
            return results

        deduped: list[SearchResult] = [results[0]]
        for r in results[1:]:
            prev = deduped[-1]
            if (
                r.source_file == prev.source_file
                and r.section_title == prev.section_title
            ):
                # Merge: combine content, keep higher score
                deduped[-1] = SearchResult(
                    content=prev.content + "\n\n" + r.content,
                    section_title=prev.section_title,
                    topic=prev.topic,
                    source_file=prev.source_file,
                    source_type=prev.source_type,
                    page_number=prev.page_number,
                    relevance_score=max(prev.relevance_score, r.relevance_score),
                )
            else:
                deduped.append(r)
        return deduped

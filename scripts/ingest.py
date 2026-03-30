"""CLI entry point for the ingestion pipeline."""

import logging
import sys
from pathlib import Path

import click

# Add project root to path for config import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "config"))

from settings import CONTENT_DIR, DB_PATH, EMBEDDING_MODEL

from ms_knowledge_base.db.operations import get_all_topics, get_sources
from ms_knowledge_base.db.schema import get_connection, initialize_db
from ms_knowledge_base.ingest.embedder import Embedder
from ms_knowledge_base.ingest.pipeline import ingest_directory, ingest_file


@click.command()
@click.option("--file", "file_path", type=click.Path(exists=True, path_type=Path), help="Ingest a single file")
@click.option("--dir", "dir_path", type=click.Path(exists=True, path_type=Path), help="Ingest a directory")
@click.option("--force", is_flag=True, help="Force re-ingestion of unchanged files")
@click.option("--stats", is_flag=True, help="Show database statistics")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=None, help="Database path")
def main(
    file_path: Path | None,
    dir_path: Path | None,
    force: bool,
    stats: bool,
    db_path: Path | None,
) -> None:
    """Ingest PDF documents into the knowledge base."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    db = db_path or DB_PATH

    if stats:
        _show_stats(db)
        return

    if not file_path and not dir_path:
        click.echo("Error: provide --file or --dir", err=True)
        raise SystemExit(1)

    # Initialize database
    initialize_db(db)

    # Load embedder once
    click.echo(f"Loading embedding model ({EMBEDDING_MODEL})...")
    embedder = Embedder(EMBEDDING_MODEL)
    click.echo("Model loaded.")

    if file_path:
        result = ingest_file(file_path, db, embedder, force=force)
        _print_result(result)
    elif dir_path:
        results = ingest_directory(dir_path, db, embedder, force=force)
        for r in results:
            _print_result(r)
        click.echo(f"\nTotal: {len(results)} files processed")


def _print_result(result) -> None:
    """Print a single ingestion result."""
    status = "created" if result.chunks_created > 0 else "skipped"
    # Replace non-ASCII chars to avoid cp1252 encoding errors on Windows
    name = result.file_path.name.encode("ascii", errors="replace").decode("ascii")
    click.echo(
        f"  {name}: {result.chunks_created} chunks {status}"
        f" | type={result.source_type}"
        f" | topics={result.topics_found}"
    )
    for err in result.errors:
        click.echo(f"    ERROR: {err}", err=True)


def _show_stats(db_path: Path) -> None:
    """Show database statistics."""
    if not db_path.exists():
        click.echo("Database not found. Run ingestion first.")
        return

    conn = get_connection(db_path)
    try:
        sources = get_sources(conn)
        topics = get_all_topics(conn)

        click.echo(f"\nSources: {len(sources)}")
        for s in sources:
            click.echo(f"  {s['file_path']}: {s['chunk_count']} chunks ({s['source_type']})")

        click.echo(f"\nTopics: {len(topics)}")
        for t in topics:
            click.echo(f"  {t['topic']}: {t['chunk_count']} chunks from {t['source_count']} sources")

        total_chunks = sum(t["chunk_count"] for t in topics)
        click.echo(f"\nTotal chunks: {total_chunks}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

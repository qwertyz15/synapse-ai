"""Ingest documents into the RAG assistant's shared library (Qdrant).

Only new, changed and deleted files are processed; re-running with no changes does nothing.
Supported types: PDF, DOCX, TXT, MD.

    python scripts/ingest.py                  # ingest ./data (RAG_DATA_DIR)
    python scripts/ingest.py --dry-run        # show what would change
    python scripts/ingest.py --full-rebuild   # re-embed everything
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import settings  # noqa: E402
from ingestion import IngestionReport, run_ingestion  # noqa: E402


def print_report(report: IngestionReport) -> None:
    prefix = "[dry run] " if report.dry_run else ""
    if report.full_rebuild:
        print(f"{prefix}Full rebuild: no manifest, embedding model changed, or --full-rebuild.")
    for label, doc_ids in [
        ("New", report.new),
        ("Updated", report.updated),
        ("Deleted", report.deleted),
    ]:
        for doc_id in doc_ids:
            print(f"{prefix}{label}: {doc_id}")
    for doc_id, error in report.failed.items():
        print(f"FAILED: {doc_id} ({error})")
    print(
        f"{prefix}{len(report.new)} new, {len(report.updated)} updated, "
        f"{len(report.deleted)} deleted, {len(report.unchanged)} unchanged, "
        f"{len(report.failed)} failed, {report.chunks_written} chunks written."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=settings.RAG_DATA_DIR, help="Folder of documents")
    parser.add_argument(
        "--db",
        default=settings.CHROMA_DB_PATH,
        help="Old Chroma folder, read once to import its manifest",
    )
    parser.add_argument("--full-rebuild", action="store_true", help="Re-embed every document")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    report = run_ingestion(
        args.source, args.db, full_rebuild=args.full_rebuild, dry_run=args.dry_run
    )
    print_report(report)
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())

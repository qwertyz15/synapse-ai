"""Copy the RAG data from the old Chroma folder (CHROMA_DB_PATH) into Qdrant.

Reuses the stored embeddings, so nothing is re-embedded; safe to run more than once.

    python scripts/migrate_chroma_to_qdrant.py            # copy
    python scripts/migrate_chroma_to_qdrant.py --dry-run  # only count what would be copied
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core import settings  # noqa: E402
from ingestion.migrate_chroma import migrate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--chroma", default=settings.CHROMA_DB_PATH, help="Chroma folder to read")
    parser.add_argument("--dry-run", action="store_true", help="Count chunks without copying")
    args = parser.parse_args()

    target = settings.QDRANT_URL or f"embedded store in {settings.QDRANT_PATH}"
    copied = migrate(args.chroma, dry_run=args.dry_run)
    if not copied:
        print(f"Nothing to migrate: no Chroma collections in {args.chroma}.")
        return
    verb = "Would copy" if args.dry_run else "Copied"
    for name, count in copied.items():
        print(f"{verb} {count} chunks from {name}")
    if not args.dry_run:
        print(f"Done. Data is now in Qdrant ({target}); the Chroma folder was left as it was.")


if __name__ == "__main__":
    main()

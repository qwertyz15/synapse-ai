import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from db.engine import session_scope
from db.models import AppMeta, LibraryDocument, utcnow

# Before the app database existed, the manifest was this SQLite file inside the Chroma folder.
MANIFEST_FILENAME = "ingestion_manifest.sqlite"
META_PREFIX = "library."
LEGACY_IMPORTED = "legacy_manifest_imported"


def list_indexed_documents(db_dir: str | Path) -> list[tuple[str, str, int, str]]:
    """(doc_id, file_type, chunk_count, ingested_at) for every indexed library document."""
    return Manifest(db_dir).documents()


class Manifest:
    """Record of which library files are indexed, kept in the app database (`library_documents`).

    `db_dir` is the Chroma folder; it is only read to import a manifest from older versions.
    """

    def __init__(self, db_dir: str | Path):
        self._import_legacy(Path(db_dir) / MANIFEST_FILENAME)

    def close(self) -> None:
        """Kept for callers written against the file-based manifest; sessions are per call."""

    def documents(self) -> list[tuple[str, str, int, str]]:
        with session_scope() as session:
            rows = session.scalars(select(LibraryDocument).order_by(LibraryDocument.doc_id))
            return [(r.doc_id, r.file_type, r.chunk_count, r.ingested_at.isoformat()) for r in rows]

    def hashes(self) -> dict[str, str]:
        with session_scope() as session:
            query = select(LibraryDocument.doc_id, LibraryDocument.content_hash)
            return {doc_id: content_hash for doc_id, content_hash in session.execute(query)}

    def get_meta(self, key: str) -> str | None:
        with session_scope() as session:
            row = session.get(AppMeta, META_PREFIX + key)
            return row.value if row else None

    def set_meta(self, key: str, value: str) -> None:
        with session_scope() as session:
            session.merge(AppMeta(key=META_PREFIX + key, value=value))

    def record(self, doc_id: str, content_hash: str, file_type: str, chunk_count: int) -> None:
        with session_scope() as session:
            session.merge(
                LibraryDocument(
                    doc_id=doc_id,
                    content_hash=content_hash,
                    file_type=file_type,
                    chunk_count=chunk_count,
                    ingested_at=utcnow(),
                )
            )

    def remove(self, doc_id: str) -> None:
        with session_scope() as session:
            session.execute(delete(LibraryDocument).where(LibraryDocument.doc_id == doc_id))

    def clear(self) -> None:
        with session_scope() as session:
            session.execute(delete(LibraryDocument))
            session.execute(delete(AppMeta).where(AppMeta.key.startswith(META_PREFIX)))
            session.merge(AppMeta(key=META_PREFIX + LEGACY_IMPORTED, value="1"))

    def _import_legacy(self, path: Path) -> None:
        if self.get_meta(LEGACY_IMPORTED):
            return
        if path.exists():
            conn = sqlite3.connect(path)
            try:
                documents = conn.execute(
                    "SELECT doc_id, content_hash, file_type, chunk_count, ingested_at FROM documents"
                ).fetchall()
                meta = conn.execute("SELECT key, value FROM meta").fetchall()
            except sqlite3.Error:
                documents, meta = [], []
            finally:
                conn.close()
            with session_scope() as session:
                for doc_id, content_hash, file_type, chunk_count, ingested_at in documents:
                    session.merge(
                        LibraryDocument(
                            doc_id=doc_id,
                            content_hash=content_hash,
                            file_type=file_type,
                            chunk_count=chunk_count,
                            ingested_at=_parse_time(ingested_at),
                        )
                    )
                for key, value in meta:
                    session.merge(AppMeta(key=META_PREFIX + key, value=value))
        self.set_meta(LEGACY_IMPORTED, "1")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return utcnow()

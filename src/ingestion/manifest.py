import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_FILENAME = "ingestion_manifest.sqlite"


class Manifest:
    """Record of what has been indexed, stored next to the vector store so the two reset together."""

    def __init__(self, db_dir: str | Path):
        db_path = Path(db_dir)
        db_path.mkdir(parents=True, exist_ok=True)
        self.path = db_path / MANIFEST_FILENAME
        self.existed = self.path.exists()
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                file_type TEXT NOT NULL,
                chunk_count INTEGER NOT NULL,
                ingested_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )

    def close(self) -> None:
        self._conn.close()

    def documents(self) -> list[tuple[str, str, int, str]]:
        """(doc_id, file_type, chunk_count, ingested_at) for every indexed document."""
        return self._conn.execute(
            "SELECT doc_id, file_type, chunk_count, ingested_at FROM documents ORDER BY doc_id"
        ).fetchall()

    def hashes(self) -> dict[str, str]:
        return dict(self._conn.execute("SELECT doc_id, content_hash FROM documents"))

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
            )

    def record(self, doc_id: str, content_hash: str, file_type: str, chunk_count: int) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?, ?, ?)",
                (doc_id, content_hash, file_type, chunk_count, datetime.now(UTC).isoformat()),
            )

    def remove(self, doc_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM documents")
            self._conn.execute("DELETE FROM meta")

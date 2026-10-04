import hashlib
from collections.abc import Iterator
from pathlib import Path

from ingestion.models import SourceDocument

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md"})


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class LocalFolderConnector:
    """Yields every supported file under a folder, recursively."""

    def __init__(self, root: str | Path, extensions: frozenset[str] = SUPPORTED_EXTENSIONS):
        self.root = Path(root)
        self.extensions = extensions

    def iter_documents(self) -> Iterator[SourceDocument]:
        if not self.root.is_dir():
            raise FileNotFoundError(f"Source folder not found: {self.root}")
        for path in sorted(self.root.rglob("*")):
            suffix = path.suffix.lower()
            if not path.is_file() or suffix not in self.extensions:
                continue
            yield SourceDocument(
                doc_id=path.relative_to(self.root).as_posix(),
                path=path,
                file_type=suffix.lstrip("."),
                content_hash=hash_file(path),
            )

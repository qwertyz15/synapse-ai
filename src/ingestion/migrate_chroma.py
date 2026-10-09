"""Copy the old Chroma collections into Qdrant, reusing their stored embeddings (no re-embedding).

Safe to re-run: chunks keep their ids, so a second run overwrites rather than duplicates.
The Chroma folder is only read.
"""

from pathlib import Path

from langchain_core.documents import Document

from ingestion.attachments import ATTACHMENTS_COLLECTION
from ingestion.index import COLLECTION_NAME
from ingestion.user_library import USER_LIBRARY_COLLECTION
from ingestion.vectors import VectorStore

COLLECTIONS = (COLLECTION_NAME, USER_LIBRARY_COLLECTION, ATTACHMENTS_COLLECTION)
PAGE = 256


def migrate(chroma_path: str | Path, dry_run: bool = False) -> dict[str, int]:
    """Chunks copied (or, with dry_run, found) per collection."""
    import chromadb

    if not Path(chroma_path).is_dir():
        return {}
    client = chromadb.PersistentClient(path=str(chroma_path))
    existing = {c.name for c in client.list_collections()}
    copied: dict[str, int] = {}
    for name in COLLECTIONS:
        if name not in existing:
            continue
        source = client.get_collection(name)
        target = VectorStore(name)
        copied[name] = 0
        for offset in range(0, source.count(), PAGE):
            page = source.get(
                limit=PAGE, offset=offset, include=["embeddings", "documents", "metadatas"]
            )
            texts, metadatas = page["documents"] or [], page["metadatas"] or []
            chunks = [
                Document(id=chunk_id, page_content=text or "", metadata=dict(meta or {}))
                for chunk_id, text, meta in zip(page["ids"], texts, metadatas)
            ]
            if not dry_run:
                vectors = page["embeddings"]  # a NumPy array, so no truthiness test
                target.add_embedded(
                    chunks, [list(v) for v in vectors] if vectors is not None else []
                )
            copied[name] += len(chunks)
    return copied

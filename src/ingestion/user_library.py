"""Each user's private library: files searchable from all of that user's chats and nobody else's.

Kept apart from the shared `rag_documents` collection, which is managed from the data folder.
"""

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ingestion.attachments import chunk_upload
from ingestion.vectors import VectorStore

USER_LIBRARY_COLLECTION = "user_library"


def open_user_library(embeddings: Embeddings | None = None) -> VectorStore:
    return VectorStore(USER_LIBRARY_COLLECTION, embeddings)


def _scope(user_id: str, name: str | None = None) -> dict[str, str]:
    return {"user_id": user_id} if name is None else {"user_id": user_id, "source": name}


def add_user_document(
    store: VectorStore,
    *,
    user_id: str,
    name: str,
    content: bytes,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    """Index one file in a user's library, replacing their earlier file with the same name."""
    chunks = chunk_upload(f"user/{user_id}/{name}", name, content, chunk_size, chunk_overlap)
    for chunk in chunks:
        chunk.metadata.update(user_id=user_id, scope="user")
    store.delete(_scope(user_id, name))
    store.add(chunks)
    return len(chunks)


def delete_user_document(store: VectorStore, user_id: str, name: str) -> bool:
    existed = store.count(_scope(user_id, name)) > 0
    if existed:
        store.delete(_scope(user_id, name))
    return existed


def search_user_library(store: VectorStore, query: str, user_id: str, k: int = 5) -> list[Document]:
    return store.search(query, k, _scope(user_id))

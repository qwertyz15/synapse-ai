"""Each user's private library: files searchable from all of that user's chats and nobody else's.

Kept apart from the shared `rag_documents` collection, which is managed from the data folder.
"""

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ingestion.attachments import chunk_upload
from ingestion.index import chroma_client

USER_LIBRARY_COLLECTION = "user_library"


def open_user_library(db_path: str | Path, embeddings: Embeddings | None = None) -> Chroma:
    return Chroma(
        collection_name=USER_LIBRARY_COLLECTION,
        client=chroma_client(db_path),
        embedding_function=embeddings,
    )


def _scope(user_id: str, name: str | None = None) -> dict:
    if name is None:
        return {"user_id": user_id}
    return {"$and": [{"user_id": user_id}, {"source": name}]}


def add_user_document(
    store: Chroma, *, user_id: str, name: str, content: bytes, chunk_size: int, chunk_overlap: int
) -> int:
    """Index one file in a user's library, replacing their earlier file with the same name."""
    chunks = chunk_upload(f"user/{user_id}/{name}", name, content, chunk_size, chunk_overlap)
    for chunk in chunks:
        chunk.metadata.update(user_id=user_id, scope="user")
    store.delete(where=_scope(user_id, name))
    store.add_documents(chunks, ids=[chunk.id for chunk in chunks])
    return len(chunks)


def delete_user_document(store: Chroma, user_id: str, name: str) -> bool:
    existing = store.get(where=_scope(user_id, name), include=[])["ids"]
    if existing:
        store.delete(ids=existing)
    return bool(existing)


def search_user_library(store: Chroma, query: str, user_id: str, k: int = 5) -> list[Document]:
    if not store.get(where=_scope(user_id), limit=1, include=[])["ids"]:
        return []
    return store.similarity_search(query, k=k, filter=_scope(user_id))

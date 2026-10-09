"""The shared library's collection, and helpers for writing a document's chunks to a collection."""

from collections.abc import Collection

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ingestion.vectors import VectorStore

COLLECTION_NAME = "rag_documents"


def open_vectorstore(embeddings: Embeddings | None = None) -> VectorStore:
    return VectorStore(COLLECTION_NAME, embeddings)


def delete_document(store: VectorStore, doc_id: str) -> None:
    store.delete({"doc_id": doc_id})


def replace_document_chunks(store: VectorStore, doc_id: str, chunks: list[Document]) -> None:
    # Delete first: an edited document may produce fewer chunks, leaving stale ids behind.
    delete_document(store, doc_id)
    store.add(chunks)


def reassign_user(
    store: VectorStore, from_user: str, to_user: str, keep: Collection[str] = ()
) -> int:
    """Re-tag a user's chunks with another user id, except files named in `keep`."""
    return store.set_fields({"user_id": from_user}, {"user_id": to_user}, exclude={"source": keep})

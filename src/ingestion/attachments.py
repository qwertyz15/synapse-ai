"""Documents attached to a single chat, searchable only from that conversation.

They live in their own collection next to the library because library ingestion removes any
indexed document that is no longer in the data folder.
"""

import tempfile
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ingestion.chunking import chunk_document
from ingestion.cleaning import clean_pages
from ingestion.loader import hash_file
from ingestion.models import SourceDocument
from ingestion.parsers import parse_untrusted
from ingestion.vectors import VectorStore

ATTACHMENTS_COLLECTION = "chat_attachments"


def open_attachment_store(embeddings: Embeddings | None = None) -> VectorStore:
    return VectorStore(ATTACHMENTS_COLLECTION, embeddings)


def _scope(thread_id: str, user_id: str, name: str | None = None) -> dict[str, str]:
    scope = {"thread_id": thread_id, "user_id": user_id}
    if name is not None:
        scope["source"] = name
    return scope


def _doc_id(thread_id: str, name: str) -> str:
    return f"{thread_id}/{name}"


def chunk_upload(
    doc_id: str, name: str, content: bytes, chunk_size: int, chunk_overlap: int
) -> list[Document]:
    """Parse an uploaded file into chunks; raises ValueError when it has no readable text."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(content)
        doc = SourceDocument(
            doc_id=doc_id,
            path=path,
            file_type=path.suffix.lower().lstrip("."),
            content_hash=hash_file(path),
        )
        chunks = chunk_document(doc, clean_pages(parse_untrusted(doc)), chunk_size, chunk_overlap)
    if not chunks:
        raise ValueError("No readable text found")
    return chunks


def add_attachment(
    store: VectorStore,
    *,
    thread_id: str,
    user_id: str,
    name: str,
    content: bytes,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    """Index one file for a chat, replacing an earlier file with the same name. Returns chunk count."""
    chunks = chunk_upload(_doc_id(thread_id, name), name, content, chunk_size, chunk_overlap)
    for chunk in chunks:
        chunk.metadata.update(thread_id=thread_id, user_id=user_id, scope="chat")
    store.delete(_scope(thread_id, user_id, name))
    store.add(chunks)
    return len(chunks)


def delete_attachment(store: VectorStore, thread_id: str, user_id: str, name: str) -> bool:
    scope = _scope(thread_id, user_id, name)
    existed = store.count(scope) > 0
    if existed:
        store.delete(scope)
    return existed


def delete_thread_attachments(store: VectorStore, thread_id: str, user_id: str) -> int:
    """Remove every file attached to a chat. Returns the number of files removed."""
    scope = _scope(thread_id, user_id)
    files = {meta["source"] for meta in store.metadatas(scope)}
    if files:
        store.delete(scope)
    return len(files)


def search_attachments(
    store: VectorStore, query: str, thread_id: str, user_id: str, k: int = 5
) -> list[Document]:
    return store.search(query, k, _scope(thread_id, user_id))

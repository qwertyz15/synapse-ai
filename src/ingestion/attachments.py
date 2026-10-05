"""Documents attached to a single chat, searchable only from that conversation.

They live in their own Chroma collection next to the library because library ingestion removes any
indexed document that is no longer in the data folder.
"""

import tempfile
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from ingestion.chunking import chunk_document
from ingestion.cleaning import clean_pages
from ingestion.index import chroma_client
from ingestion.loader import hash_file
from ingestion.models import SourceDocument
from ingestion.parsers import parse

ATTACHMENTS_COLLECTION = "chat_attachments"


def open_attachment_store(db_path: str | Path, embeddings: Embeddings | None = None) -> Chroma:
    return Chroma(
        collection_name=ATTACHMENTS_COLLECTION,
        client=chroma_client(db_path),
        embedding_function=embeddings,
    )


def _scope(thread_id: str, user_id: str, name: str | None = None) -> dict:
    conditions: list[dict] = [{"thread_id": thread_id}, {"user_id": user_id}]
    if name is not None:
        conditions.append({"source": name})
    return {"$and": conditions}


def _doc_id(thread_id: str, name: str) -> str:
    return f"{thread_id}/{name}"


def add_attachment(
    store: Chroma,
    *,
    thread_id: str,
    user_id: str,
    name: str,
    content: bytes,
    chunk_size: int,
    chunk_overlap: int,
) -> int:
    """Index one file for a chat, replacing an earlier file with the same name. Returns chunk count."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(content)
        doc = SourceDocument(
            doc_id=_doc_id(thread_id, name),
            path=path,
            file_type=path.suffix.lower().lstrip("."),
            content_hash=hash_file(path),
        )
        chunks = chunk_document(doc, clean_pages(parse(doc)), chunk_size, chunk_overlap)
    if not chunks:
        raise ValueError("No readable text found")
    for chunk in chunks:
        chunk.metadata.update(thread_id=thread_id, user_id=user_id, scope="chat")
    store.delete(where=_scope(thread_id, user_id, name))
    store.add_documents(chunks, ids=[chunk.id for chunk in chunks])
    return len(chunks)


def list_attachments(
    store: Chroma, thread_id: str, user_id: str
) -> list[tuple[str, str, int, str]]:
    """(name, file_type, chunk_count, ingested_at) for each file attached to the chat."""
    metadatas = store.get(where=_scope(thread_id, user_id), include=["metadatas"])["metadatas"]
    files: dict[str, tuple[str, str, int, str]] = {}
    for meta in metadatas:
        name = str(meta["source"])
        _, file_type, count, ingested_at = files.get(
            name, (name, str(meta["file_type"]), 0, str(meta["ingested_at"]))
        )
        files[name] = (name, file_type, count + 1, ingested_at)
    return sorted(files.values())


def delete_attachment(store: Chroma, thread_id: str, user_id: str, name: str) -> bool:
    existing = store.get(where=_scope(thread_id, user_id, name), include=[])["ids"]
    if existing:
        store.delete(ids=existing)
    return bool(existing)


def delete_thread_attachments(store: Chroma, thread_id: str, user_id: str) -> int:
    """Remove every file attached to a chat. Returns the number of files removed."""
    found = store.get(where=_scope(thread_id, user_id), include=["metadatas"])
    if found["ids"]:
        store.delete(ids=found["ids"])
    return len({meta["source"] for meta in found["metadatas"]})


def search_attachments(
    store: Chroma, query: str, thread_id: str, user_id: str, k: int = 5
) -> list[Document]:
    if not store.get(where=_scope(thread_id, user_id), limit=1, include=[])["ids"]:
        return []
    return store.similarity_search(query, k=k, filter=_scope(thread_id, user_id))

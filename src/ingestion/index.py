import threading
from collections.abc import Collection
from pathlib import Path

import chromadb
from chromadb.api.shared_system_client import SharedSystemClient
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

COLLECTION_NAME = "rag_documents"
CHROMA_FILE = "chroma.sqlite3"

_clients: dict[str, chromadb.ClientAPI] = {}
_clients_lock = threading.Lock()


def chroma_client(db_path: str | Path) -> chromadb.ClientAPI:
    # Chroma's client setup races when threads create clients for the same path at once
    # (parallel tool calls), failing with KeyError / "Could not connect to tenant".
    key = str(Path(db_path).resolve())
    with _clients_lock:
        if key in _clients and not (Path(key) / CHROMA_FILE).exists():
            # The folder was deleted while we ran; the cached client would keep using the gone
            # database. Chroma can only drop its cache wholesale, so reconnect every path.
            SharedSystemClient.clear_system_cache()
            _clients.clear()
        if key not in _clients:
            _clients[key] = chromadb.PersistentClient(path=key)
        return _clients[key]


def open_vectorstore(db_path: str | Path, embeddings: Embeddings) -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        client=chroma_client(db_path),
        embedding_function=embeddings,
    )


def delete_document(store: Chroma, doc_id: str) -> None:
    store.delete(where={"doc_id": doc_id})


def replace_document_chunks(store: Chroma, doc_id: str, chunks: list[Document]) -> None:
    # Delete first: an edited document may produce fewer chunks, leaving stale ids behind.
    delete_document(store, doc_id)
    if chunks:
        store.add_documents(chunks, ids=[chunk.id for chunk in chunks])


def reassign_user(store: Chroma, from_user: str, to_user: str, keep: Collection[str] = ()) -> int:
    """Re-tag a user's chunks with another user id, except files named in `keep`."""
    found = store.get(where={"user_id": from_user}, include=["metadatas"])
    ids, metadatas = [], []
    for chunk_id, metadata in zip(found["ids"], found["metadatas"]):
        if metadata.get("source") in keep:
            continue
        ids.append(chunk_id)
        metadatas.append({**metadata, "user_id": to_user})
    if ids:
        store._collection.update(ids=ids, metadatas=metadatas)
    return len(ids)

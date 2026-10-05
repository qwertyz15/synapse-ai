import threading
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

COLLECTION_NAME = "rag_documents"

_clients: dict[str, chromadb.ClientAPI] = {}
_clients_lock = threading.Lock()


def chroma_client(db_path: str | Path) -> chromadb.ClientAPI:
    # Chroma's client setup races when threads create clients for the same path at once
    # (parallel tool calls), failing with KeyError / "Could not connect to tenant".
    key = str(Path(db_path).resolve())
    with _clients_lock:
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

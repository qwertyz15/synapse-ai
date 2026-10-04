from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

COLLECTION_NAME = "rag_documents"


def open_vectorstore(db_path: str | Path, embeddings: Embeddings) -> Chroma:
    return Chroma(
        collection_name=COLLECTION_NAME,
        persist_directory=str(db_path),
        embedding_function=embeddings,
    )


def delete_document(store: Chroma, doc_id: str) -> None:
    store.delete(where={"doc_id": doc_id})


def replace_document_chunks(store: Chroma, doc_id: str, chunks: list[Document]) -> None:
    # Delete first: an edited document may produce fewer chunks, leaving stale ids behind.
    delete_document(store, doc_id)
    if chunks:
        store.add_documents(chunks, ids=[chunk.id for chunk in chunks])

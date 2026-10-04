from datetime import UTC, datetime

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ingestion.models import ParsedPage, SourceDocument

DEFAULT_ACL = "public"


def build_metadata(doc: SourceDocument, page: int | None, ingested_at: str) -> dict[str, str | int]:
    metadata: dict[str, str | int] = {
        "doc_id": doc.doc_id,
        "source": doc.path.name,
        "file_type": doc.file_type,
        "content_hash": doc.content_hash,
        "ingested_at": ingested_at,
        # Placeholder until per-user permissions exist; lets retrieval filter on it later.
        "acl": DEFAULT_ACL,
    }
    # Chroma rejects None metadata values, so pageless formats omit the key.
    if page is not None:
        metadata["page"] = page
    return metadata


def chunk_document(
    doc: SourceDocument, pages: list[ParsedPage], chunk_size: int, chunk_overlap: int
) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    ingested_at = datetime.now(UTC).isoformat()
    chunks: list[Document] = []
    for page in pages:
        metadata = build_metadata(doc, page.page, ingested_at)
        for text in splitter.split_text(page.text):
            chunks.append(
                Document(id=f"{doc.doc_id}#{len(chunks)}", page_content=text, metadata=metadata)
            )
    return chunks

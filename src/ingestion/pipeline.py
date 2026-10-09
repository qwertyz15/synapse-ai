import logging
from pathlib import Path

from langchain_core.embeddings import Embeddings

from core import settings
from core.embeddings import embedding_signature, get_embeddings
from ingestion.changes import detect_changes
from ingestion.chunking import chunk_document
from ingestion.cleaning import clean_pages
from ingestion.index import delete_document, open_vectorstore, replace_document_chunks
from ingestion.loader import LocalFolderConnector
from ingestion.manifest import Manifest
from ingestion.models import IngestionReport
from ingestion.parsers import parse

logger = logging.getLogger(__name__)

SIGNATURE_KEY = "embedding_signature"


def run_ingestion(
    source_dir: str | Path,
    db_path: str | Path,
    *,
    embeddings: Embeddings | None = None,
    signature: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    full_rebuild: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    """Bring the vector store in line with the source folder, touching only what changed.

    The index is rebuilt from scratch when there is no manifest, when the embedding
    provider/model changed (old vectors would be incompatible), or when asked to.
    """
    signature = signature or embedding_signature()
    chunk_size = chunk_size or settings.RAG_CHUNK_SIZE
    chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.RAG_CHUNK_OVERLAP
    documents = list(LocalFolderConnector(source_dir).iter_documents())
    report = IngestionReport(dry_run=dry_run)

    manifest = Manifest(db_path)
    try:
        indexed = manifest.hashes()
        report.full_rebuild = (
            full_rebuild
            or manifest.get_meta(SIGNATURE_KEY) != signature
            # The index says files are embedded but the vectors are gone (the store was emptied).
            or (bool(indexed) and open_vectorstore().count() == 0)
        )
        if report.full_rebuild:
            indexed = {}
        changes = detect_changes(documents, indexed)
        report.unchanged = [doc.doc_id for doc in changes.unchanged]
        report.deleted = changes.deleted

        if dry_run:
            report.new = [doc.doc_id for doc in changes.new]
            report.updated = [doc.doc_id for doc in changes.updated]
            return report

        store = open_vectorstore(embeddings or get_embeddings())
        if report.full_rebuild:
            store.reset()
            manifest.clear()
            manifest.set_meta(SIGNATURE_KEY, signature)

        for doc_id in changes.deleted:
            delete_document(store, doc_id)
            manifest.remove(doc_id)

        to_index = [(doc, report.new) for doc in changes.new]
        to_index += [(doc, report.updated) for doc in changes.updated]
        for doc, bucket in to_index:
            try:
                chunks = chunk_document(doc, clean_pages(parse(doc)), chunk_size, chunk_overlap)
                replace_document_chunks(store, doc.doc_id, chunks)
            except Exception as e:
                # Left out of the manifest so the next run retries it.
                logger.exception("Failed to ingest %s", doc.doc_id)
                report.failed[doc.doc_id] = f"{type(e).__name__}: {e}"
                continue
            manifest.record(doc.doc_id, doc.content_hash, doc.file_type, len(chunks))
            bucket.append(doc.doc_id)
            report.chunks_written += len(chunks)
        return report
    finally:
        manifest.close()

"""Endpoints for managing the RAG assistant's documents.

Ingestion runs here, next to the vector store, because the Streamlit app may run in a
separate container without access to the data folder or database.
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from core import settings
from ingestion import IngestionReport, run_ingestion
from ingestion.loader import SUPPORTED_EXTENSIONS
from ingestion.manifest import list_indexed_documents
from schema import IngestionResult, RagDocument, RagDocuments

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

router = APIRouter(prefix="/rag", tags=["rag"])

# Concurrent runs would race on the manifest and on deleting/re-adding the same chunks.
_ingestion_lock = asyncio.Lock()


def _data_dir() -> Path:
    return Path(settings.RAG_DATA_DIR).resolve()


async def _ingest() -> IngestionReport:
    async with _ingestion_lock:
        try:
            return await run_in_threadpool(
                run_ingestion, settings.RAG_DATA_DIR, settings.CHROMA_DB_PATH
            )
        except ValueError as e:
            # Raised for missing embedding configuration, e.g. no API key.
            raise HTTPException(status_code=503, detail=str(e))
        except Exception:
            logger.exception("Ingestion failed")
            raise HTTPException(status_code=500, detail="Ingestion failed")


def _result(report: IngestionReport, rejected: dict[str, str] | None = None) -> IngestionResult:
    return IngestionResult(
        new=report.new,
        updated=report.updated,
        deleted=report.deleted,
        unchanged=report.unchanged,
        failed=report.failed,
        rejected=rejected or {},
        chunks_written=report.chunks_written,
        full_rebuild=report.full_rebuild,
    )


@router.get("/documents")
def list_documents() -> RagDocuments:
    """List the documents currently indexed for the RAG assistant."""
    return RagDocuments(
        documents=[
            RagDocument(doc_id=d, file_type=t, chunk_count=c, ingested_at=at)
            for d, t, c, at in list_indexed_documents(settings.CHROMA_DB_PATH)
        ]
    )


@router.post("/documents")
async def upload_documents(files: list[UploadFile]) -> IngestionResult:
    """
    Save uploaded files to the data folder and ingest them.

    A file with the same name as an existing one replaces it. Unsupported or oversized
    files are listed in `rejected`; files that fail to parse are listed in `failed`.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    rejected: dict[str, str] = {}
    for upload in files:
        # Path.name drops any directory parts a client sends, preventing path traversal.
        name = Path(upload.filename or "").name
        if not name or name.startswith("."):
            rejected[upload.filename or ""] = "Invalid filename"
            continue
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            rejected[name] = f"Unsupported type; use {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            continue
        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            rejected[name] = f"Larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            continue
        (data_dir / name).write_bytes(content)

    if len(rejected) == len(files):
        return IngestionResult(rejected=rejected)
    return _result(await _ingest(), rejected)


@router.delete("/documents/{doc_id:path}")
async def delete_document(doc_id: str) -> IngestionResult:
    """Delete a document's file and remove it from the index."""
    data_dir = _data_dir()
    target = (data_dir / doc_id).resolve()
    if not target.is_relative_to(data_dir) or target == data_dir:
        raise HTTPException(status_code=400, detail="Invalid document id")
    if target.is_file():
        target.unlink()
    elif doc_id not in {d.doc_id for d in list_documents().documents}:
        raise HTTPException(status_code=404, detail="Document not found")
    return _result(await _ingest())

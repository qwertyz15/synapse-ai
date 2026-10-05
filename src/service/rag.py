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
from core.embeddings import get_embeddings
from db import chats as chat_rows
from db.engine import async_session_scope
from ingestion import IngestionReport, run_ingestion
from ingestion.attachments import (
    add_attachment,
    delete_attachment,
    delete_thread_attachments,
    open_attachment_store,
)
from ingestion.loader import SUPPORTED_EXTENSIONS
from ingestion.manifest import list_indexed_documents
from schema import (
    AttachmentResult,
    ChatAttachment,
    ChatAttachments,
    IngestionResult,
    RagDocument,
    RagDocuments,
)

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


async def _read_uploads(files: list[UploadFile]) -> tuple[dict[str, bytes], dict[str, str]]:
    """Accepted name -> content, and rejected name -> reason."""
    accepted: dict[str, bytes] = {}
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
        accepted[name] = content
    return accepted, rejected


@router.post("/documents")
async def upload_documents(files: list[UploadFile]) -> IngestionResult:
    """
    Save uploaded files to the data folder and ingest them.

    A file with the same name as an existing one replaces it. Unsupported or oversized
    files are listed in `rejected`; files that fail to parse are listed in `failed`.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    accepted, rejected = await _read_uploads(files)
    for name, content in accepted.items():
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


async def _attachments(thread_id: str, user_id: str) -> list[ChatAttachment]:
    async with async_session_scope() as session:
        rows = await chat_rows.list_attachments(session, thread_id, user_id)
    return [
        ChatAttachment(
            name=r.name,
            file_type=r.file_type,
            chunk_count=r.chunk_count,
            ingested_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/attachments")
async def list_chat_attachments(thread_id: str, user_id: str) -> ChatAttachments:
    """List the files attached to one chat."""
    return ChatAttachments(attachments=await _attachments(thread_id, user_id))


@router.post("/attachments")
async def attach_to_chat(thread_id: str, user_id: str, files: list[UploadFile]) -> AttachmentResult:
    """
    Index files for a single chat. They are searchable only from that conversation (and user),
    alongside the shared library. A file with the same name replaces the earlier one.
    """
    accepted, rejected = await _read_uploads(files)
    attached: list[str] = []
    failed: dict[str, str] = {}
    if accepted:
        try:
            embeddings = get_embeddings()
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))
        store = open_attachment_store(settings.CHROMA_DB_PATH, embeddings)
        async with _ingestion_lock:
            for name, content in accepted.items():
                try:
                    chunks = await run_in_threadpool(
                        add_attachment,
                        store,
                        thread_id=thread_id,
                        user_id=user_id,
                        name=name,
                        content=content,
                        chunk_size=settings.RAG_CHUNK_SIZE,
                        chunk_overlap=settings.RAG_CHUNK_OVERLAP,
                    )
                except Exception as e:
                    logger.exception("Failed to attach %s", name)
                    failed[name] = f"{type(e).__name__}: {e}"
                    continue
                async with async_session_scope() as session:
                    await chat_rows.upsert_attachment(
                        session,
                        thread_id,
                        user_id,
                        name,
                        Path(name).suffix.lstrip(".").lower(),
                        chunks,
                    )
                attached.append(name)
    return AttachmentResult(
        attached=attached,
        failed=failed,
        rejected=rejected,
        attachments=await _attachments(thread_id, user_id),
    )


@router.delete("/attachments/{name:path}")
async def detach_from_chat(name: str, thread_id: str, user_id: str) -> ChatAttachments:
    """Remove a file attached to a chat."""
    store = open_attachment_store(settings.CHROMA_DB_PATH)
    async with _ingestion_lock:
        removed_chunks = await run_in_threadpool(delete_attachment, store, thread_id, user_id, name)
    async with async_session_scope() as session:
        removed_row = await chat_rows.delete_attachment(session, thread_id, user_id, name)
    if not removed_chunks and not removed_row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return ChatAttachments(attachments=await _attachments(thread_id, user_id))


async def remove_thread_attachments(thread_id: str, user_id: str) -> int:
    """Delete every file attached to a chat (used when the chat itself is deleted)."""
    if not Path(settings.CHROMA_DB_PATH).is_dir():
        return 0
    store = open_attachment_store(settings.CHROMA_DB_PATH)
    async with _ingestion_lock:
        return await run_in_threadpool(delete_thread_attachments, store, thread_id, user_id)

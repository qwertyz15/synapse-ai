"""Endpoints for managing the RAG assistant's documents.

Ingestion runs here, next to the vector store, because the Streamlit app may run in a
separate container without access to the data folder or database.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from core import settings
from core.embeddings import get_embeddings
from db import chats as chat_rows
from db import user_documents as user_rows
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
from ingestion.user_library import add_user_document, delete_user_document, open_user_library
from schema import (
    AttachmentResult,
    ChatAttachment,
    ChatAttachments,
    IngestionResult,
    RagDocument,
    RagDocuments,
)
from service.locks import ingestion_lock
from service.plans import upload_limits

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 10
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024

router = APIRouter(prefix="/rag", tags=["rag"])


def _data_dir() -> Path:
    return Path(settings.RAG_DATA_DIR).resolve()


async def _ingest() -> IngestionReport:
    async with ingestion_lock:
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
    """List the documents in the shared library (the data folder)."""
    return RagDocuments(
        documents=[
            RagDocument(doc_id=d, file_type=t, chunk_count=c, ingested_at=at, shared=True)
            for d, t, c, at in list_indexed_documents(settings.CHROMA_DB_PATH)
        ]
    )


async def _read_uploads(
    files: list[UploadFile], max_mb: int | None = None
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Accepted name -> content, and rejected name -> reason."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=413, detail=f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time"
        )
    max_bytes = min(MAX_UPLOAD_BYTES, max_mb * 1024 * 1024) if max_mb else MAX_UPLOAD_BYTES
    accepted: dict[str, bytes] = {}
    rejected: dict[str, str] = {}
    total = 0
    for upload in files:
        # Path.name drops any directory parts a client sends, preventing path traversal.
        name = Path(upload.filename or "").name
        if not name or name.startswith("."):
            rejected[upload.filename or ""] = "Invalid filename"
            continue
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            rejected[name] = f"Unsupported type; use {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            continue
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            rejected[name] = f"Larger than {max_bytes // (1024 * 1024)} MB"
            continue
        if total + len(content) > MAX_TOTAL_UPLOAD_BYTES:
            rejected[name] = (
                f"Over the {MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)} MB limit per upload; "
                "send it separately"
            )
            continue
        total += len(content)
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


async def _user_documents(user_id: str) -> list[RagDocument]:
    async with async_session_scope() as session:
        rows = await user_rows.list_user_documents(session, user_id)
    return [
        RagDocument(
            doc_id=r.name,
            file_type=r.file_type,
            chunk_count=r.chunk_count,
            ingested_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/my-documents")
async def list_my_documents(user_id: str) -> RagDocuments:
    """List a user's own library, followed by the shared library they can search but not change."""
    return RagDocuments(documents=[*await _user_documents(user_id), *list_documents().documents])


@router.post("/my-documents")
async def upload_my_documents(user_id: str, files: list[UploadFile]) -> IngestionResult:
    """Add files to a user's own library, searchable from all of their chats and nobody else's.

    Free accounts have a smaller file size limit and a cap on how many files the library holds;
    replacing a file with the same name doesn't count against the cap.
    """
    max_mb, max_files = await upload_limits(user_id)
    accepted, rejected = await _read_uploads(files, max_mb)
    if max_files is not None:
        existing = {d.doc_id for d in await _user_documents(user_id)}
        free_slots = max_files - len(existing)
        for name in list(accepted):
            if name in existing:
                continue
            if free_slots > 0:
                free_slots -= 1
            else:
                del accepted[name]
                rejected[name] = f"Your library is full ({max_files} files on the free plan)"
    result = IngestionResult(rejected=rejected)
    if not accepted:
        return result
    try:
        embeddings = get_embeddings()
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    store = open_user_library(settings.CHROMA_DB_PATH, embeddings)
    async with ingestion_lock:
        for name, content in accepted.items():
            try:
                chunks = await run_in_threadpool(
                    add_user_document,
                    store,
                    user_id=user_id,
                    name=name,
                    content=content,
                    chunk_size=settings.RAG_CHUNK_SIZE,
                    chunk_overlap=settings.RAG_CHUNK_OVERLAP,
                )
            except Exception as e:
                logger.exception("Failed to add %s to a user library", name)
                result.failed[name] = f"{type(e).__name__}: {e}"
                continue
            async with async_session_scope() as session:
                replaced = await user_rows.upsert_user_document(
                    session, user_id, name, Path(name).suffix.lstrip(".").lower(), chunks
                )
            (result.updated if replaced else result.new).append(name)
            result.chunks_written += chunks
    return result


@router.delete("/my-documents/{name:path}")
async def delete_my_document(name: str, user_id: str) -> IngestionResult:
    """Remove a file from a user's own library."""
    store = open_user_library(settings.CHROMA_DB_PATH)
    async with ingestion_lock:
        removed_chunks = await run_in_threadpool(delete_user_document, store, user_id, name)
    async with async_session_scope() as session:
        removed_row = await user_rows.delete_user_document(session, user_id, name)
    if not removed_chunks and not removed_row:
        raise HTTPException(status_code=404, detail="Document not found")
    return IngestionResult(deleted=[name])


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
    max_mb, _ = await upload_limits(user_id)
    accepted, rejected = await _read_uploads(files, max_mb)
    attached: list[str] = []
    failed: dict[str, str] = {}
    if accepted:
        try:
            embeddings = get_embeddings()
        except ValueError as e:
            raise HTTPException(status_code=503, detail=str(e))
        store = open_attachment_store(settings.CHROMA_DB_PATH, embeddings)
        async with ingestion_lock:
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
    async with ingestion_lock:
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
    async with ingestion_lock:
        return await run_in_threadpool(delete_thread_attachments, store, thread_id, user_id)

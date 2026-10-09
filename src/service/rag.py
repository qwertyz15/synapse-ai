"""Endpoints for managing the RAG assistant's documents.

Ingestion runs here, next to the vector store, because the Streamlit app may run in a
separate container without access to the data folder or database.
"""

import logging
import shutil
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from sqlalchemy import delete, select, update
from starlette.concurrency import run_in_threadpool

from core import settings
from core.embeddings import get_embeddings
from db import chats as chat_rows
from db import user_documents as user_rows
from db.engine import async_session_scope
from db.models import IngestionJob, utcnow
from ingestion import IngestionReport, run_ingestion
from ingestion.attachments import (
    delete_attachment,
    delete_thread_attachments,
    open_attachment_store,
)
from ingestion.jobs import Outcome, RetryLater, give_up, run_job, upload_path
from ingestion.loader import SUPPORTED_EXTENSIONS
from ingestion.manifest import list_indexed_documents
from ingestion.user_library import delete_user_document, open_user_library
from schema import (
    AttachmentResult,
    ChatAttachment,
    ChatAttachments,
    IngestionJobInfo,
    IngestionJobs,
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
        existing |= {j.name for j in await _open_jobs(user_id, "library") if j.status != "failed"}
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
    _require_embeddings()
    for name, outcome in await _submit(user_id, "library", None, accepted):
        if outcome is None:
            result.queued.append(name)
        elif outcome.status == "ready":
            (result.updated if outcome.replaced else result.new).append(name)
            result.chunks_written += outcome.chunks
        else:
            result.failed[name] = outcome.error or "Indexing failed"
    return result


@router.delete("/my-documents/{name:path}")
async def delete_my_document(name: str, user_id: str) -> IngestionResult:
    """Remove a file from a user's own library."""
    store = open_user_library()
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
    queued: list[str] = []
    failed: dict[str, str] = {}
    if accepted:
        _require_embeddings()
        for name, outcome in await _submit(user_id, "attachment", thread_id, accepted):
            if outcome is None:
                queued.append(name)
            elif outcome.status == "ready":
                attached.append(name)
            else:
                failed[name] = outcome.error or "Indexing failed"
    return AttachmentResult(
        attached=attached,
        queued=queued,
        failed=failed,
        rejected=rejected,
        attachments=await _attachments(thread_id, user_id),
    )


@router.delete("/attachments/{name:path}")
async def detach_from_chat(name: str, thread_id: str, user_id: str) -> ChatAttachments:
    """Remove a file attached to a chat."""
    store = open_attachment_store()
    async with ingestion_lock:
        removed_chunks = await run_in_threadpool(delete_attachment, store, thread_id, user_id, name)
    async with async_session_scope() as session:
        removed_row = await chat_rows.delete_attachment(session, thread_id, user_id, name)
    if not removed_chunks and not removed_row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return ChatAttachments(attachments=await _attachments(thread_id, user_id))


async def remove_thread_attachments(thread_id: str, user_id: str) -> int:
    """Delete every file attached to a chat (used when the chat itself is deleted)."""
    store = open_attachment_store()
    async with ingestion_lock:
        return await run_in_threadpool(delete_thread_attachments, store, thread_id, user_id)


def _require_embeddings() -> None:
    try:
        get_embeddings()
    except ValueError as e:
        # Missing embedding configuration, e.g. no API key: fail before anything is queued.
        raise HTTPException(status_code=503, detail=str(e))


def _write_upload(job_id: str, name: str, content: bytes) -> None:
    path = upload_path(job_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def _run_inline(job_id: str) -> Outcome:
    try:
        return await run_in_threadpool(run_job, job_id)
    except RetryLater as e:
        # Inline there's no worker to retry later; the user can retry the job.
        await run_in_threadpool(give_up, job_id, str(e))
        return Outcome(status="failed", error=str(e))


async def _dispatch(job_ids: list[str]) -> dict[str, Outcome | None]:
    """Queue the jobs for the worker, or (without REDIS_URL) index them now. None means queued."""
    if settings.REDIS_URL:
        from worker.tasks import enqueue

        outcomes: dict[str, Outcome | None] = {}
        for job_id in job_ids:
            try:
                await run_in_threadpool(enqueue, job_id)
                outcomes[job_id] = None
            except Exception:
                logger.exception("Couldn't queue job %s", job_id)
                message = "Couldn't queue the file for indexing; try again."
                await run_in_threadpool(give_up, job_id, message)
                outcomes[job_id] = Outcome(status="failed", error=message)
        return outcomes
    async with ingestion_lock:
        return {job_id: await _run_inline(job_id) for job_id in job_ids}


async def _submit(
    user_id: str, kind: str, thread_id: str | None, files: dict[str, bytes]
) -> list[tuple[str, Outcome | None]]:
    """Create an indexing job per file, store the files, then queue or run the jobs."""
    job_ids = {name: str(uuid4()) for name in files}
    async with async_session_scope() as session:
        for name, job_id in job_ids.items():
            session.add(
                IngestionJob(id=job_id, user_id=user_id, kind=kind, thread_id=thread_id, name=name)
            )
    for name, content in files.items():
        await run_in_threadpool(_write_upload, job_ids[name], name, content)
    outcomes = await _dispatch(list(job_ids.values()))
    return [(name, outcomes[job_id]) for name, job_id in job_ids.items()]


async def _open_jobs(user_id: str, kind: str, thread_id: str | None = None) -> list[IngestionJob]:
    async with async_session_scope() as session:
        query = select(IngestionJob).where(
            IngestionJob.user_id == user_id,
            IngestionJob.kind == kind,
            IngestionJob.status != "ready",
        )
        if thread_id is not None:
            query = query.where(IngestionJob.thread_id == thread_id)
        return list(await session.scalars(query.order_by(IngestionJob.created_at)))


def _job_info(job: IngestionJob) -> IngestionJobInfo:
    return IngestionJobInfo(
        id=job.id,
        name=job.name,
        kind=job.kind,  # type: ignore[arg-type]
        thread_id=job.thread_id,
        status=job.status,  # type: ignore[arg-type]
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/jobs")
async def list_jobs(user_id: str, thread_id: str | None = None) -> IngestionJobs:
    """Uploads still queued or indexing, or that failed: for the user's library, or one chat."""
    kind = "attachment" if thread_id else "library"
    return IngestionJobs(jobs=[_job_info(j) for j in await _open_jobs(user_id, kind, thread_id)])


async def _own_job(job_id: str, user_id: str) -> IngestionJob:
    async with async_session_scope() as session:
        job = await session.get(IngestionJob, job_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(status_code=404, detail="Upload not found")
    return job


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, user_id: str) -> IngestionJobInfo:
    """Try a failed upload again (its file is kept until it's indexed or dismissed)."""
    job = await _own_job(job_id, user_id)
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed uploads can be retried")
    if not upload_path(job.id, job.name).is_file():
        raise HTTPException(status_code=410, detail="The uploaded file is gone; upload it again.")
    _require_embeddings()
    async with async_session_scope() as session:
        row = await session.get(IngestionJob, job_id)
        if row is not None:
            row.status, row.error, row.updated_at = "queued", None, utcnow()
    await _dispatch([job_id])
    return _job_info(await _own_job(job_id, user_id))


@router.delete("/jobs/{job_id}")
async def dismiss_job(job_id: str, user_id: str) -> IngestionJobs:
    """Drop a queued or failed upload and its stored file."""
    job = await _own_job(job_id, user_id)
    if job.status == "indexing":
        raise HTTPException(status_code=409, detail="This upload is being indexed right now")
    async with async_session_scope() as session:
        await session.execute(delete(IngestionJob).where(IngestionJob.id == job_id))
    shutil.rmtree(upload_path(job.id, job.name).parent, ignore_errors=True)
    return await list_jobs(user_id, job.thread_id)


async def remove_thread_jobs(thread_id: str, user_id: str) -> None:
    """Drop a deleted chat's pending uploads and their files."""
    for job in await _open_jobs(user_id, "attachment", thread_id):
        shutil.rmtree(upload_path(job.id, job.name).parent, ignore_errors=True)
    async with async_session_scope() as session:
        await session.execute(
            delete(IngestionJob).where(
                IngestionJob.thread_id == thread_id, IngestionJob.user_id == user_id
            )
        )


async def recover_jobs() -> None:
    """At startup: forget finished jobs older than a week, and (without a worker) fail jobs a
    restart interrupted so the user can retry them."""
    async with async_session_scope() as session:
        await session.execute(
            delete(IngestionJob).where(
                IngestionJob.status == "ready",
                IngestionJob.updated_at < utcnow() - timedelta(days=7),
            )
        )
        if not settings.REDIS_URL:
            await session.execute(
                update(IngestionJob)
                .where(IngestionJob.status.in_(("queued", "indexing")))
                .values(status="failed", error="Interrupted by a restart; retry it.")
            )

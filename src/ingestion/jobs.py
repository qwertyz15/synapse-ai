"""Indexing one uploaded file as a job: queued → indexing → ready or failed.

Shared by the Celery worker and by the service when it indexes inline (no REDIS_URL). It only needs
the app database, the uploads folder, embeddings and the vector store, so the worker stays small.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core import settings
from core.embeddings import get_embeddings
from db.engine import session_scope
from db.models import ChatAttachment, IngestionJob, UserDocument, utcnow
from ingestion.attachments import add_attachment, open_attachment_store
from ingestion.user_library import add_user_document, open_user_library

# Libraries whose errors may clear up on retry (rate limits, timeouts, dropped connections).
_PROVIDER_MODULES = {"openai", "voyageai", "google", "httpx", "httpcore", "langchain_google_genai"}


class RetryLater(Exception):
    """A temporary failure: the job went back to `queued` and is worth trying again."""


@dataclass
class Outcome:
    status: str
    chunks: int = 0
    replaced: bool = False
    error: str | None = None


def upload_path(job_id: str, name: str) -> Path:
    return Path(settings.UPLOADS_DIR) / job_id / name


def is_temporary(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    if type(error).__module__.split(".")[0] not in _PROVIDER_MODULES:
        return False
    status = getattr(error, "status_code", None)
    text = str(error)
    return status in (408, 429, 500, 502, 503, 504) or any(
        hint in text for hint in ("429", "RESOURCE_EXHAUSTED", "rate limit", "timed out", "Timeout")
    )


def _message(error: BaseException) -> str:
    text = str(error) if isinstance(error, ValueError) else f"{type(error).__name__}: {error}"
    return text[:300]


def _record(session, model: type, keys: dict[str, Any], values: dict[str, Any]) -> bool:
    """Insert or update the file's row; True when it replaced an earlier file of the same name."""
    row = session.scalar(select(model).filter_by(**keys))
    if row is None:
        session.add(model(**keys, **values))
        return False
    for field, value in values.items():
        setattr(row, field, value)
    return True


def _finish(job_id: str, **fields: Any) -> None:
    with session_scope() as session:
        job = session.get(IngestionJob, job_id)
        if job is not None:
            for field, value in {**fields, "updated_at": utcnow()}.items():
                setattr(job, field, value)


def run_job(job_id: str) -> Outcome:
    """Index the job's file. Raises RetryLater for temporary failures (the job is `queued` again)."""
    with session_scope() as session:
        job = session.get(IngestionJob, job_id)
        if job is None or job.status == "ready":
            return Outcome(status=job.status if job else "missing")
        job.status, job.attempts, job.error, job.updated_at = (
            "indexing",
            job.attempts + 1,
            None,
            utcnow(),
        )
        kind, user_id, thread_id, name = job.kind, job.user_id, job.thread_id, job.name

    path = upload_path(job_id, name)
    try:
        content = path.read_bytes()
        embeddings = get_embeddings()
        options = dict(
            name=name,
            content=content,
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
        )
        if kind == "library":
            chunks = add_user_document(open_user_library(embeddings), user_id=user_id, **options)
        else:
            chunks = add_attachment(
                open_attachment_store(embeddings),
                thread_id=str(thread_id),
                user_id=user_id,
                **options,
            )
    except FileNotFoundError:
        _finish(job_id, status="failed", error="The uploaded file is gone; upload it again.")
        return Outcome(status="failed", error="The uploaded file is gone; upload it again.")
    except Exception as e:
        if is_temporary(e):
            _finish(job_id, status="queued", error=_message(e))
            raise RetryLater(_message(e)) from e
        _finish(job_id, status="failed", error=_message(e))
        return Outcome(status="failed", error=_message(e))

    file_type = Path(name).suffix.lstrip(".").lower()
    with session_scope() as session:
        if kind == "library":
            replaced = _record(
                session,
                UserDocument,
                {"user_id": user_id, "name": name},
                {"file_type": file_type, "chunk_count": chunks, "created_at": utcnow()},
            )
        else:
            replaced = _record(
                session,
                ChatAttachment,
                {"thread_id": thread_id, "user_id": user_id, "name": name},
                {"file_type": file_type, "chunk_count": chunks, "created_at": utcnow()},
            )
        job = session.get(IngestionJob, job_id)
        if job is not None:
            job.status, job.chunk_count, job.replaced, job.updated_at = (
                "ready",
                chunks,
                replaced,
                utcnow(),
            )
    shutil.rmtree(path.parent, ignore_errors=True)
    return Outcome(status="ready", chunks=chunks, replaced=replaced)


def give_up(job_id: str, reason: str) -> None:
    """Mark a job failed after its retries ran out (its file stays, so it can be retried later)."""
    _finish(job_id, status="failed", error=reason[:300])

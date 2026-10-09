"""Running an upload job: ready, replaced, failed for good, or back in the queue for a retry."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from core.settings import settings
from db.engine import session_scope
from db.models import ChatAttachment, IngestionJob, UserDocument
from ingestion import jobs
from ingestion.user_library import open_user_library

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture(autouse=True)
def env(tmp_path):
    with (
        patch.object(settings, "UPLOADS_DIR", str(tmp_path / "uploads")),
        patch.object(settings, "RAG_CHUNK_SIZE", 100),
        patch.object(settings, "RAG_CHUNK_OVERLAP", 0),
        patch.object(jobs, "get_embeddings", return_value=EMBEDDINGS),
    ):
        yield


def _job(name="plan.txt", content=b"Bluebird plan. " * 20, kind="library", thread_id=None) -> str:
    job_id = str(uuid4())
    with session_scope() as session:
        session.add(
            IngestionJob(id=job_id, user_id="u1", kind=kind, thread_id=thread_id, name=name)
        )
    path = jobs.upload_path(job_id, name)
    if content is not None:
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    return job_id


def _status(job_id):
    with session_scope() as session:
        job = session.get(IngestionJob, job_id)
        return job.status, job.error, job.attempts


def test_indexes_into_the_library_and_cleans_up():
    job_id = _job()
    outcome = jobs.run_job(job_id)
    assert outcome.status == "ready" and outcome.chunks > 1 and not outcome.replaced
    assert _status(job_id) == ("ready", None, 1)
    assert not jobs.upload_path(job_id, "plan.txt").parent.exists()
    with session_scope() as session:
        assert session.query(UserDocument).filter_by(user_id="u1", name="plan.txt").count() == 1
    assert open_user_library(EMBEDDINGS).search("Bluebird", 1, {"user_id": "u1"})

    assert jobs.run_job(_job(content=b"Edited plan.")).replaced


def test_chat_attachments_get_their_row():
    jobs.run_job(_job(kind="attachment", thread_id="t1", name="notes.md"))
    with session_scope() as session:
        assert session.query(ChatAttachment).filter_by(thread_id="t1", name="notes.md").count() == 1


def test_bad_files_fail_for_good_and_keep_the_file():
    job_id = _job(name="empty.txt", content=b"   ")
    assert jobs.run_job(job_id).status == "failed"
    assert _status(job_id)[:2] == ("failed", "No readable text found")
    assert jobs.upload_path(job_id, "empty.txt").exists()

    gone = _job(content=None)
    assert jobs.run_job(gone).status == "failed" and "gone" in _status(gone)[1]


def test_temporary_provider_errors_go_back_to_the_queue():
    error = type("RateLimitError", (Exception,), {"__module__": "openai"})("429 Too Many Requests")
    job_id = _job()
    with patch.object(jobs, "add_user_document", side_effect=error), pytest.raises(jobs.RetryLater):
        jobs.run_job(job_id)
    assert _status(job_id)[0] == "queued"

    jobs.give_up(job_id, "Still rate limited after 3 tries")
    assert _status(job_id)[:2] == ("failed", "Still rate limited after 3 tries")

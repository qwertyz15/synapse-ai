"""Uploads as jobs: queued for the worker with Redis, retried, dismissed and cleaned up."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from core.settings import settings
from db.chats import claim_chat
from db.engine import async_session_scope
from ingestion.jobs import run_job, upload_path
from service import app
from service.rag import recover_jobs

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture
def client(tmp_path):
    with (
        patch.object(settings, "UPLOADS_DIR", str(tmp_path / "uploads")),
        patch.object(settings, "RAG_CHUNK_SIZE", 100),
        patch.object(settings, "RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
        patch("ingestion.jobs.get_embeddings", return_value=EMBEDDINGS),
    ):
        yield TestClient(app)


@pytest.fixture
def queued():
    """Redis configured; the queue is replaced by a list of job ids."""
    sent: list[str] = []
    with (
        patch.object(settings, "REDIS_URL", "redis://test"),
        patch("worker.tasks.enqueue", side_effect=sent.append),
    ):
        yield sent


def _upload(client, user="u1", *files):
    return client.post(
        "/rag/my-documents", params={"user_id": user}, files=[("files", f) for f in files]
    )


def _jobs(client, user="u1", thread=None):
    params = {"user_id": user, **({"thread_id": thread} if thread else {})}
    return client.get("/rag/jobs", params=params).json()["jobs"]


def _library(client, user="u1"):
    return [
        d["doc_id"]
        for d in client.get("/rag/my-documents", params={"user_id": user}).json()["documents"]
    ]


def test_with_redis_uploads_are_queued_then_indexed_by_the_worker(client, queued):
    body = _upload(client, "u1", ("plan.txt", b"Bluebird plan. " * 10)).json()
    assert body["queued"] == ["plan.txt"] and body["new"] == []
    [job] = _jobs(client)
    assert (job["name"], job["status"]) == ("plan.txt", "queued") and queued == [job["id"]]
    assert _library(client) == []

    assert run_job(job["id"]).status == "ready"
    assert _jobs(client) == [] and _library(client) == ["plan.txt"]


def test_a_failed_queue_marks_the_job_failed_and_retry_works(client, queued):
    with patch("worker.tasks.enqueue", side_effect=ConnectionError("redis down")):
        body = _upload(client, "u1", ("plan.txt", b"Bluebird plan. " * 10)).json()
    assert "Couldn't queue" in body["failed"]["plan.txt"]
    [job] = _jobs(client)
    assert job["status"] == "failed"

    retried = client.post(f"/rag/jobs/{job['id']}/retry", params={"user_id": "u1"}).json()
    assert retried["status"] == "queued" and queued == [job["id"]]
    assert client.post(f"/rag/jobs/{job['id']}/retry", params={"user_id": "u2"}).status_code == 404


def test_queued_files_count_toward_the_free_library_cap(client, queued):
    with (
        patch.object(settings, "DEFAULT_PLAN", "free"),
        patch.object(settings, "FREE_LIBRARY_FILES", 1),
    ):
        body = {"google_sub": "g-cap", "email": "cap@x.com", "email_verified": True}
        user = client.post("/auth/sign-in", json=body).json()["id"]
        assert _upload(client, user, ("a.txt", b"one")).json()["queued"] == ["a.txt"]
        assert (
            "library is full"
            in _upload(client, user, ("b.txt", b"two")).json()["rejected"]["b.txt"]
        )


def test_dismissing_a_job_removes_its_file(client, queued):
    _upload(client, "u1", ("plan.txt", b"Plan."))
    [job] = _jobs(client)
    path = upload_path(job["id"], "plan.txt")
    assert path.is_file()
    assert client.delete(f"/rag/jobs/{job['id']}", params={"user_id": "u1"}).json() == {"jobs": []}
    assert not path.parent.exists()


@pytest.mark.asyncio
async def test_deleting_a_chat_drops_its_pending_uploads(client, queued, mock_agent):
    async with async_session_scope() as session:
        await claim_chat(session, "t1", "u1", "research-assistant", "hello")
    client.post(
        "/rag/attachments",
        params={"thread_id": "t1", "user_id": "u1"},
        files=[("files", ("notes.txt", b"Notes."))],
    )
    [job] = _jobs(client, thread="t1")
    with patch("service.service.thread_owner", return_value=None):
        client.delete("/research-assistant/threads/t1", params={"user_id": "u1"})
    assert _jobs(client, thread="t1") == []
    assert not Path(upload_path(job["id"], "notes.txt")).parent.exists()


@pytest.mark.asyncio
async def test_without_redis_a_restart_fails_interrupted_jobs(client, queued):
    _upload(client, "u1", ("plan.txt", b"Plan."))
    with patch.object(settings, "REDIS_URL", None):
        await recover_jobs()
    [job] = _jobs(client)
    assert job["status"] == "failed" and "restart" in job["error"]

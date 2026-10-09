"""Free accounts upload smaller files and keep fewer of them in their library."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from core.settings import settings
from service import app

EMBEDDINGS = DeterministicFakeEmbedding(size=16)
MB = 1024 * 1024


@pytest.fixture
def client(tmp_path):
    with (
        patch("service.rag.settings.CHROMA_DB_PATH", str(tmp_path / "db")),
        # Large chunks: these tests are about file sizes, not chunking, and fewer chunks index fast.
        patch("service.rag.settings.RAG_CHUNK_SIZE", 100_000),
        patch("service.rag.settings.RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
        patch("ingestion.jobs.get_embeddings", return_value=EMBEDDINGS),
        patch.object(settings, "ADMIN_EMAILS", "boss@x.com"),
        patch.object(settings, "DEFAULT_PLAN", "free"),
        patch.object(settings, "FREE_MAX_FILE_MB", 1),
        patch.object(settings, "FREE_LIBRARY_FILES", 2),
    ):
        yield TestClient(app)


def _account(client, email):
    body = {"google_sub": f"sub-{email}", "email": email, "email_verified": True}
    return client.post("/auth/sign-in", json=body).json()["id"]


def _upload(client, user, *files):
    return client.post(
        "/rag/my-documents", params={"user_id": user}, files=[("files", f) for f in files]
    ).json()


BIG = b"word " * (MB // 5 + 10)


def test_free_files_are_smaller_than_admin_files(client):
    free, boss = _account(client, "ana@x.com"), _account(client, "boss@x.com")
    assert "big.txt" in _upload(client, free, ("big.txt", BIG))["rejected"]
    assert _upload(client, boss, ("big.txt", BIG))["new"] == ["big.txt"]


def test_free_library_holds_a_limited_number_of_files(client):
    free = _account(client, "ana@x.com")
    body = _upload(client, free, ("a.txt", b"one"), ("b.txt", b"two"), ("c.txt", b"three"))
    assert body["new"] == ["a.txt", "b.txt"]
    assert "library is full" in body["rejected"]["c.txt"]
    assert _upload(client, free, ("a.txt", b"one, edited"))["updated"] == ["a.txt"]
    assert "d.txt" in _upload(client, free, ("d.txt", b"four"))["rejected"]

    boss = _account(client, "boss@x.com")
    many = [(f"{i}.txt", b"text") for i in range(5)]
    assert len(_upload(client, boss, *many)["new"]) == 5


def test_free_chat_attachments_use_the_smaller_file_limit(client):
    free = _account(client, "ana@x.com")
    body = client.post(
        "/rag/attachments",
        params={"thread_id": "t1", "user_id": free},
        files=[("files", ("big.txt", BIG))],
    ).json()
    assert "big.txt" in body["rejected"]

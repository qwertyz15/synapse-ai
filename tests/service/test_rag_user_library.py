"""Each user's own library: private to them and searched from all of their chats."""

from functools import partial
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from agents.tools import database_search_func
from ingestion import run_ingestion
from service import app

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture
def rag_env(tmp_path):
    db = str(tmp_path / "db")
    fake_ingestion = partial(
        run_ingestion, embeddings=EMBEDDINGS, signature="fake:test", chunk_size=100, chunk_overlap=0
    )
    with (
        patch("service.rag.settings.RAG_DATA_DIR", str(tmp_path / "data")),
        patch("service.rag.settings.CHROMA_DB_PATH", db),
        patch("service.rag.settings.RAG_CHUNK_SIZE", 100),
        patch("service.rag.settings.RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.run_ingestion", fake_ingestion),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
        patch("agents.tools.get_embeddings", return_value=EMBEDDINGS),
    ):
        yield db


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, user, *files):
    return client.post(
        "/rag/my-documents", params={"user_id": user}, files=[("files", f) for f in files]
    )


def _names(client, user):
    docs = client.get("/rag/my-documents", params={"user_id": user}).json()["documents"]
    return [(d["doc_id"], d["shared"]) for d in docs]


def test_each_user_sees_only_their_own_documents(client, rag_env):
    body = _upload(client, "u1", ("plan.txt", b"Project Zephyr plan. " * 10)).json()
    assert body["new"] == ["plan.txt"] and body["chunks_written"] > 0

    assert _names(client, "u1") == [("plan.txt", False)]
    assert _names(client, "u2") == []


def test_reupload_replaces_and_delete_is_scoped(client, rag_env):
    _upload(client, "u1", ("plan.txt", b"First version."))
    assert _upload(client, "u1", ("plan.txt", b"Second version.")).json()["updated"] == ["plan.txt"]

    assert client.delete("/rag/my-documents/plan.txt", params={"user_id": "u2"}).status_code == 404
    assert _names(client, "u1") == [("plan.txt", False)]

    response = client.delete("/rag/my-documents/plan.txt", params={"user_id": "u1"})
    assert response.json()["deleted"] == ["plan.txt"]
    assert _names(client, "u1") == []


def test_rejects_bad_files_and_reports_unreadable_ones(client, rag_env):
    body = _upload(client, "u1", ("x.exe", b"bin"), ("empty.txt", b"   ")).json()
    assert "x.exe" in body["rejected"]
    assert "empty.txt" in body["failed"]
    assert _names(client, "u1") == []


def test_search_uses_own_library_and_shared_library_only(client, rag_env):
    client.post("/rag/documents", files=[("files", ("handbook.txt", b"Shared handbook text."))])
    _upload(client, "u1", ("mine.txt", b"Private note of user one."))
    _upload(client, "u2", ("theirs.txt", b"Private note of user two."))

    found = database_search_func("note", {"configurable": {"thread_id": "t1", "user_id": "u1"}})
    assert "Private note of user one." in found
    assert "Shared handbook text." in found
    assert "user two" not in found


def test_listing_includes_shared_library_as_read_only(client, rag_env):
    client.post("/rag/documents", files=[("files", ("handbook.txt", b"Shared handbook text."))])
    _upload(client, "u1", ("mine.txt", b"Mine."))
    assert _names(client, "u1") == [("mine.txt", False), ("handbook.txt", True)]

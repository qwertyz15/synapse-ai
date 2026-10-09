"""Files attached to one chat: scoped by thread and user, searched together with the library."""

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


def _attach(client, thread="t1", user="u1", *files):
    return client.post(
        "/rag/attachments",
        params={"thread_id": thread, "user_id": user},
        files=[("files", f) for f in files],
    )


def _list(client, thread="t1", user="u1"):
    response = client.get("/rag/attachments", params={"thread_id": thread, "user_id": user})
    return [a["name"] for a in response.json()["attachments"]]


def test_attachments_are_scoped_to_chat_and_user(client, rag_env):
    response = _attach(client, "t1", "u1", ("notes.txt", b"Zephyr budget is 42 dollars. " * 10))
    assert response.status_code == 200
    body = response.json()
    assert body["attached"] == ["notes.txt"]
    assert body["attachments"][0]["chunk_count"] > 0

    assert _list(client, "t1", "u1") == ["notes.txt"]
    assert _list(client, "t2", "u1") == []
    assert _list(client, "t1", "someone-else") == []


def test_rejects_bad_files_and_reports_unreadable_ones(client, rag_env):
    body = _attach(client, "t1", "u1", ("x.exe", b"bin"), ("empty.txt", b"   ")).json()
    assert "x.exe" in body["rejected"]
    assert "empty.txt" in body["failed"]
    assert body["attachments"] == []


def test_search_covers_chat_attachments_and_library(client, rag_env):
    client.post("/rag/documents", files=[("files", ("handbook.txt", b"Library handbook text."))])
    _attach(client, "t1", "u1", ("notes.txt", b"Chat-only notes."))

    in_chat = database_search_func("notes", {"configurable": {"thread_id": "t1", "user_id": "u1"}})
    assert "(attached to this chat)" in in_chat
    assert "Chat-only notes." in in_chat
    assert "Library handbook text." in in_chat

    other_chat = database_search_func(
        "notes", {"configurable": {"thread_id": "t2", "user_id": "u1"}}
    )
    assert "Chat-only notes." not in other_chat
    assert "Library handbook text." in other_chat


def test_library_reindexing_keeps_attachments(client, rag_env):
    _attach(client, "t1", "u1", ("notes.txt", b"Chat-only notes."))
    client.post("/rag/documents", files=[("files", ("a.txt", b"Library text."))])
    client.delete("/rag/documents/a.txt")
    assert _list(client) == ["notes.txt"]


def test_replace_and_delete_attachment(client, rag_env):
    _attach(client, "t1", "u1", ("notes.txt", b"First version."))
    _attach(client, "t1", "u1", ("notes.txt", b"Second version."))
    assert _list(client) == ["notes.txt"]
    found = database_search_func("version", {"configurable": {"thread_id": "t1", "user_id": "u1"}})
    assert "Second version." in found and "First version." not in found

    response = client.delete(
        "/rag/attachments/notes.txt", params={"thread_id": "t1", "user_id": "u1"}
    )
    assert response.status_code == 200
    assert response.json()["attachments"] == []
    missing = client.delete(
        "/rag/attachments/notes.txt", params={"thread_id": "t1", "user_id": "u1"}
    )
    assert missing.status_code == 404


def test_parallel_searches(client, rag_env):
    """Parallel tool calls search at once; the embedded store must serialize them safely."""
    import concurrent.futures as cf

    client.post("/rag/documents", files=[("files", ("handbook.txt", b"Library handbook text."))])
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
    with cf.ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda i: database_search_func(f"q{i}", config), range(6)))
    assert all("Library handbook text." in r for r in results)

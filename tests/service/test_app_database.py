"""The app database: migrations, chat ownership, attachments and the library index."""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlalchemy import inspect

from db import backfill
from db.chats import ChatAccessError, claim_chat, get_chat, list_attachments
from db.engine import async_session_scope, get_engine
from ingestion import run_ingestion
from ingestion.manifest import MANIFEST_FILENAME, Manifest
from service import app

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


def test_migrations_create_the_tables():
    tables = set(inspect(get_engine()).get_table_names())
    assert {
        "chats",
        "chat_attachments",
        "library_documents",
        "app_meta",
        "alembic_version",
    } <= tables


@pytest.mark.asyncio
async def test_claim_creates_then_bumps_and_guards_ownership():
    async with async_session_scope() as session:
        chat = await claim_chat(session, "t1", "alice", "research-assistant", "  Hello\n world  ")
        assert chat.title == "Hello world"
        first_update = chat.updated_at

    async with async_session_scope() as session:
        again = await claim_chat(session, "t1", "alice", "research-assistant", "second message")
        assert again.title == "Hello world"
        assert again.updated_at >= first_update

    for user, agent in (("mallory", "research-assistant"), ("alice", "chatbot")):
        with pytest.raises(ChatAccessError):
            async with async_session_scope() as session:
                await claim_chat(session, "t1", user, agent, "hi")

    async with async_session_scope() as session:
        continued = await claim_chat(session, "t1", None, "research-assistant", "no user id")
        assert continued.user_id == "alice"


def test_stream_records_the_chat_and_refuses_other_users(mock_agent):
    client = TestClient(app)
    body = {"message": "What is our PTO policy?", "thread_id": "t-web", "user_id": "alice"}
    assert client.post("/research-assistant/stream", json=body).status_code == 200

    listed = client.get("/chats", params={"user_id": "alice"}).json()["threads"]
    assert [(t["thread_id"], t["title"]) for t in listed] == [("t-web", "What is our PTO policy?")]

    stolen = client.post("/research-assistant/stream", json={**body, "user_id": "mallory"})
    assert stolen.status_code == 404
    assert client.get("/chats", params={"user_id": "mallory"}).json()["threads"] == []


@pytest.fixture
def rag_env(tmp_path):
    db = str(tmp_path / "chroma")
    with (
        patch("service.rag.settings.CHROMA_DB_PATH", db),
        patch("service.rag.settings.RAG_CHUNK_SIZE", 100),
        patch("service.rag.settings.RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
        patch("ingestion.jobs.get_embeddings", return_value=EMBEDDINGS),
    ):
        yield db


@pytest.mark.asyncio
async def test_attachments_are_recorded_and_removed_with_the_chat(rag_env, mock_agent):
    client = TestClient(app)
    params = {"thread_id": "t1", "user_id": "alice"}
    client.post("/research-assistant/stream", json={"message": "hi", **params})
    client.post(
        "/rag/attachments", params=params, files=[("files", ("cv.md", b"Experience. " * 20))]
    )

    async with async_session_scope() as session:
        [row] = await list_attachments(session, "t1", "alice")
        assert (row.name, row.file_type) == ("cv.md", "md") and row.chunk_count > 0

    with patch("service.service.thread_owner", return_value=None):
        response = client.delete("/research-assistant/threads/t1", params={"user_id": "alice"})
    assert response.status_code == 200
    async with async_session_scope() as session:
        assert await list_attachments(session, "t1", "alice") == []
        assert await get_chat(session, "t1") is None


@pytest.mark.asyncio
async def test_backfill_imports_attachments_already_indexed(rag_env):
    from ingestion.attachments import add_attachment, open_attachment_store

    store = open_attachment_store(EMBEDDINGS)
    add_attachment(
        store,
        thread_id="t1",
        user_id="alice",
        name="notes.txt",
        content=b"Old notes. " * 30,
        chunk_size=100,
        chunk_overlap=0,
    )

    assert await backfill.backfill_attachments() == 1
    assert await backfill.backfill_attachments() == 0
    async with async_session_scope() as session:
        [row] = await list_attachments(session, "t1", "alice")
    assert row.name == "notes.txt" and row.chunk_count > 1


def test_manifest_imports_the_old_sqlite_file(tmp_path):
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    old = sqlite3.connect(chroma_dir / MANIFEST_FILENAME)
    old.executescript(
        """
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, content_hash TEXT, file_type TEXT,
                                chunk_count INTEGER, ingested_at TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO documents VALUES ('handbook.pdf', 'abc', 'pdf', 3, '2026-10-04T19:40:58+00:00');
        INSERT INTO meta VALUES ('embedding_signature', 'voyage:voyage-4-lite');
        """
    )
    old.commit()
    old.close()

    manifest = Manifest(chroma_dir)
    assert manifest.hashes() == {"handbook.pdf": "abc"}
    assert manifest.get_meta("embedding_signature") == "voyage:voyage-4-lite"
    assert manifest.documents()[0][:3] == ("handbook.pdf", "pdf", 3)


def test_emptied_vector_store_triggers_a_full_rebuild(tmp_path):
    from ingestion.index import open_vectorstore

    data, chroma = tmp_path / "data", tmp_path / "chroma"
    data.mkdir()
    (data / "a.txt").write_text("Alpha " * 40)
    kwargs = {"embeddings": EMBEDDINGS, "signature": "fake", "chunk_size": 100, "chunk_overlap": 0}

    assert run_ingestion(data, chroma, **kwargs).new == ["a.txt"]
    assert run_ingestion(data, chroma, **kwargs).unchanged == ["a.txt"]

    open_vectorstore().reset()
    rebuilt = run_ingestion(data, chroma, **kwargs)
    assert rebuilt.full_rebuild and rebuilt.new == ["a.txt"]

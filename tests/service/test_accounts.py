"""Google sign-in on the service side: who may join, stable accounts, and claiming anonymous data."""

from functools import partial
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from agents.tools import database_search_func
from core.settings import settings
from db.chats import claim_chat
from db.engine import async_session_scope
from ingestion import run_ingestion
from service import app

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rag_env(tmp_path):
    fake_ingestion = partial(
        run_ingestion, embeddings=EMBEDDINGS, signature="fake:test", chunk_size=100, chunk_overlap=0
    )
    with (
        patch("service.rag.settings.RAG_DATA_DIR", str(tmp_path / "data")),
        patch("service.rag.settings.CHROMA_DB_PATH", str(tmp_path / "db")),
        patch("service.rag.settings.RAG_CHUNK_SIZE", 100),
        patch("service.rag.settings.RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.run_ingestion", fake_ingestion),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
        patch("agents.tools.get_embeddings", return_value=EMBEDDINGS),
    ):
        yield


def _sign_in(client, sub="g-1", email="ana@example.com", **extra):
    body = {"google_sub": sub, "email": email, "email_verified": True, "name": "Ana", **extra}
    return client.post("/auth/sign-in", json=body)


def test_creates_a_stable_account_and_flags_admins(client):
    with patch.object(settings, "ADMIN_EMAILS", "Boss@Example.com, other@x.com"):
        first = _sign_in(client).json()
        again = _sign_in(client, name="Ana B.").json()
        boss = _sign_in(client, sub="g-2", email="boss@example.com").json()
    assert first["id"] == again["id"] and again["name"] == "Ana B."
    assert first["is_admin"] is False and boss["is_admin"] is True


def test_refuses_unverified_emails(client):
    assert _sign_in(client, email_verified=False).status_code == 403


@pytest.mark.parametrize(
    ("signups", "allowed", "email", "status"),
    [
        ("open", "", "anyone@x.com", 200),
        ("invite", "friend@x.com,@uni.edu", "friend@x.com", 200),
        ("invite", "friend@x.com,@uni.edu", "student@uni.edu", 200),
        ("invite", "friend@x.com,@uni.edu", "stranger@x.com", 403),
        ("closed", "", "anyone@x.com", 403),
        ("closed", "", "admin@x.com", 200),
    ],
)
def test_signup_rules(client, signups, allowed, email, status):
    with (
        patch.object(settings, "SIGNUPS", signups),
        patch.object(settings, "ALLOWED_EMAILS", allowed),
        patch.object(settings, "ADMIN_EMAILS", "admin@x.com"),
    ):
        assert _sign_in(client, sub=f"sub-{email}", email=email).status_code == status


def test_existing_accounts_can_sign_in_after_signups_close(client):
    _sign_in(client)
    with patch.object(settings, "SIGNUPS", "closed"):
        assert _sign_in(client).status_code == 200


@pytest.mark.asyncio
async def test_anonymous_chats_and_files_move_to_the_account(client, rag_env):
    async with async_session_scope() as session:
        await claim_chat(session, "anon-chat", "anon-1", "research-assistant", "hello")
    client.post(
        "/rag/attachments",
        params={"thread_id": "anon-chat", "user_id": "anon-1"},
        files=[("files", ("notes.txt", b"Attached Zephyr notes."))],
    )
    for name, text in [("plan.txt", b"Anonymous Bluebird plan."), ("dup.txt", b"Anon copy.")]:
        client.post(
            "/rag/my-documents", params={"user_id": "anon-1"}, files=[("files", (name, text))]
        )

    user_id = _sign_in(client).json()["id"]
    client.post(
        "/rag/my-documents", params={"user_id": user_id}, files=[("files", ("dup.txt", b"Mine."))]
    )
    _sign_in(client, anonymous_user_id="anon-1")

    chats = client.get("/chats", params={"user_id": user_id}).json()["threads"]
    assert [c["thread_id"] for c in chats] == ["anon-chat"]
    attachments = client.get(
        "/rag/attachments", params={"thread_id": "anon-chat", "user_id": user_id}
    ).json()["attachments"]
    assert [a["name"] for a in attachments] == ["notes.txt"]
    mine = client.get("/rag/my-documents", params={"user_id": user_id}).json()["documents"]
    assert sorted(d["doc_id"] for d in mine) == ["dup.txt", "plan.txt"]
    left = client.get("/rag/my-documents", params={"user_id": "anon-1"}).json()["documents"]
    assert [d["doc_id"] for d in left] == ["dup.txt"]

    found = database_search_func(
        "plan", {"configurable": {"thread_id": "anon-chat", "user_id": user_id}}
    )
    assert "Anonymous Bluebird plan." in found and "Attached Zephyr notes." in found
    assert "Anon copy." not in found

"""Renaming a chat: only its owner can, and the new title sticks."""

import pytest
from fastapi.testclient import TestClient

from db.chats import claim_chat
from db.engine import async_session_scope
from service import app


@pytest.fixture
def client():
    return TestClient(app)


async def _claim(thread_id: str, user_id: str, message: str = "hello"):
    async with async_session_scope() as session:
        await claim_chat(session, thread_id, user_id, "research-assistant", message)


def _rename(client, thread_id: str, user_id: str, title: str):
    return client.patch(
        f"/research-assistant/threads/{thread_id}",
        params={"user_id": user_id},
        json={"title": title},
    )


def _titles(client, user_id: str):
    threads = client.get("/chats", params={"user_id": user_id}).json()["threads"]
    return {t["thread_id"]: t["title"] for t in threads}


@pytest.mark.asyncio
async def test_owner_renames_and_title_survives_new_messages(client):
    await _claim("rename-1", "u1")
    response = _rename(client, "rename-1", "u1", "  Trip planning  ")
    assert response.status_code == 200
    assert response.json()["title"] == "Trip planning"

    await _claim("rename-1", "u1", "a later message")
    assert _titles(client, "u1")["rename-1"] == "Trip planning"


@pytest.mark.asyncio
async def test_other_users_and_agents_get_404(client):
    await _claim("rename-2", "u1")
    assert _rename(client, "rename-2", "u2", "Mine now").status_code == 404
    other_agent = client.patch(
        "/chatbot/threads/rename-2", params={"user_id": "u1"}, json={"title": "x"}
    )
    assert other_agent.status_code == 404
    assert _rename(client, "missing", "u1", "x").status_code == 404
    assert _titles(client, "u1")["rename-2"] == "hello"


@pytest.mark.asyncio
async def test_rejects_blank_and_overlong_titles(client):
    await _claim("rename-3", "u1")
    assert _rename(client, "rename-3", "u1", "   ").status_code == 422
    assert _rename(client, "rename-3", "u1", "x" * 201).status_code == 422

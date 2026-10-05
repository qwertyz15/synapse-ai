"""Deleting a chat removes its checkpoints and the files attached to it."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from service import app

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture
def graph():
    saver = InMemorySaver()
    compiled = (
        StateGraph(MessagesState)
        .add_node("reply", lambda state: {"messages": [("ai", "hi")]})
        .add_edge(START, "reply")
        .compile(checkpointer=saver)
    )
    with patch("service.service.get_agent", return_value=compiled):
        yield compiled


@pytest.fixture
def attachments_db(tmp_path):
    with (
        patch("service.rag.settings.CHROMA_DB_PATH", str(tmp_path / "db")),
        patch("service.rag.settings.RAG_CHUNK_SIZE", 100),
        patch("service.rag.settings.RAG_CHUNK_OVERLAP", 0),
        patch("service.rag.get_embeddings", return_value=EMBEDDINGS),
    ):
        yield


@pytest.fixture
def client():
    return TestClient(app)


async def _chat(graph, thread_id: str, user_id: str, agent_id: str = "research-assistant"):
    config = {
        "configurable": {"thread_id": thread_id, "user_id": user_id},
        "metadata": {"user_id": user_id, "agent_id": agent_id},
    }
    await graph.ainvoke({"messages": [("user", "hello")]}, config)


def _attach(client, thread_id: str, user_id: str):
    return client.post(
        "/rag/attachments",
        params={"thread_id": thread_id, "user_id": user_id},
        files=[("files", ("notes.txt", b"Attached notes. " * 5))],
    )


def _delete(client, thread_id: str, user_id: str):
    return client.delete(f"/research-assistant/threads/{thread_id}", params={"user_id": user_id})


@pytest.mark.asyncio
async def test_delete_removes_messages_and_attachments(client, graph, attachments_db):
    await _chat(graph, "t1", "u1")
    _attach(client, "t1", "u1")

    response = _delete(client, "t1", "u1")
    assert response.status_code == 200
    assert response.json() == {"thread_id": "t1", "attachments_removed": 1}

    assert await graph.checkpointer.aget_tuple({"configurable": {"thread_id": "t1"}}) is None
    listed = client.get("/rag/attachments", params={"thread_id": "t1", "user_id": "u1"})
    assert listed.json()["attachments"] == []


@pytest.mark.asyncio
async def test_cannot_delete_someone_elses_chat(client, graph, attachments_db):
    await _chat(graph, "t1", "owner")
    _attach(client, "t1", "owner")

    assert _delete(client, "t1", "intruder").status_code == 404
    assert await graph.checkpointer.aget_tuple({"configurable": {"thread_id": "t1"}}) is not None
    listed = client.get("/rag/attachments", params={"thread_id": "t1", "user_id": "owner"})
    assert [a["name"] for a in listed.json()["attachments"]] == ["notes.txt"]


@pytest.mark.asyncio
async def test_cannot_delete_through_another_agent(client, graph, attachments_db):
    await _chat(graph, "t1", "u1", agent_id="chatbot")
    assert _delete(client, "t1", "u1").status_code == 404


def test_deletes_attachments_of_a_chat_that_was_never_sent(client, graph, attachments_db):
    _attach(client, "draft", "u1")
    response = _delete(client, "draft", "u1")
    assert response.status_code == 200
    assert response.json()["attachments_removed"] == 1


def test_unknown_chat_is_404(client, graph, attachments_db):
    assert _delete(client, "nope", "u1").status_code == 404


@pytest.mark.asyncio
async def test_history_of_a_deleted_chat_is_empty(client, graph, attachments_db):
    await _chat(graph, "t1", "u1")
    _delete(client, "t1", "u1")
    response = client.post("/research-assistant/history", json={"thread_id": "t1"})
    assert response.status_code == 200
    assert response.json() == {"messages": []}

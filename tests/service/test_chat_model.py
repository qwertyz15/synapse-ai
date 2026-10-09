"""Each chat remembers the model its latest message used."""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from core.settings import settings
from schema.models import DeepseekModelName

FLASH = DeepseekModelName.DEEPSEEK_V4_FLASH
PRO = DeepseekModelName.DEEPSEEK_V4_PRO


@pytest.fixture
def client(test_client, mock_agent):
    mock_agent.ainvoke.return_value = [("values", {"messages": [AIMessage(content="ok")]})]
    with (
        patch.object(settings, "AVAILABLE_MODELS", {FLASH, PRO}),
        patch.object(settings, "DEFAULT_MODEL", FLASH),
    ):
        yield test_client


def _send(client, thread, model=None):
    body = {"message": "hi", "user_id": "u1", "thread_id": thread}
    if model:
        body["model"] = model
    assert client.post("/invoke", json=body).status_code == 200


def _models(client):
    return {
        t["thread_id"]: t["model"]
        for t in client.get("/chats", params={"user_id": "u1"}).json()["threads"]
    }


def test_chats_remember_their_latest_model(client):
    _send(client, "c1", PRO)
    _send(client, "c2")
    assert _models(client) == {"c1": PRO, "c2": FLASH}

    _send(client, "c1", FLASH)
    assert _models(client)["c1"] == FLASH


def test_history_includes_the_model(client):
    _send(client, "c3", PRO)
    history = client.post("/history", json={"thread_id": "c3", "user_id": "u1"}).json()
    assert history["model"] == PRO

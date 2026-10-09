"""Chats run on the user's own key for that provider, outside the plan's limits."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from core.llm import user_key_for
from core.settings import settings
from schema.models import AnthropicModelName, DeepseekModelName
from service import user_keys

FLASH = DeepseekModelName.DEEPSEEK_V4_FLASH
HAIKU = AnthropicModelName.HAIKU_45
KEY = "sk-ant-user-key-0042"


@pytest.fixture
def setup(test_client, mock_agent):
    seen: list[str | None] = []

    async def run(**kwargs):
        seen.append(user_key_for(HAIKU))
        return [("values", {"messages": [AIMessage(content="ok")]})]

    mock_agent.ainvoke = AsyncMock(side_effect=run)
    with (
        patch.object(settings, "USER_KEYS_SECRET", SecretStr("keys-secret")),
        patch.object(settings, "DEFAULT_PLAN", "free"),
        patch.object(settings, "FREE_MESSAGES_PER_DAY", 1),
        patch.object(settings, "FREE_MODELS", str(FLASH)),
        patch.object(settings, "AVAILABLE_MODELS", {FLASH}),
        patch.object(settings, "DEFAULT_MODEL", FLASH),
        patch.object(user_keys, "verify_key", AsyncMock(return_value=True)),
    ):
        body = {"google_sub": "g-own", "email": "own@x.com", "email_verified": True}
        user = test_client.post("/auth/sign-in", json=body).json()["id"]
        yield test_client, user, seen, mock_agent


def _send(client, user, model):
    return client.post("/invoke", json={"message": "hi", "user_id": user, "model": model})


def test_own_key_unlocks_its_models_without_a_cap(setup):
    client, user, seen, _ = setup
    assert _send(client, user, HAIKU).status_code == 403
    client.put("/auth/keys/anthropic", params={"user_id": user}, json={"api_key": KEY})

    assert [_send(client, user, HAIKU).status_code for _ in range(3)] == [200, 200, 200]
    assert seen == [KEY, KEY, KEY]
    assert [_send(client, user, FLASH).status_code for _ in range(2)] == [200, 429]

    plan = client.get("/auth/plan", params={"user_id": user}).json()
    assert plan["own_key_providers"] == ["anthropic"]
    assert plan["models"][0] == FLASH and HAIKU in plan["models"]
    assert plan["messages_today"] == 1


def test_streams_run_with_the_key_too(setup):
    client, user, _, agent = setup
    client.put("/auth/keys/anthropic", params={"user_id": user}, json={"api_key": KEY})
    seen = []

    async def stream(**kwargs):
        seen.append(user_key_for(HAIKU))
        return
        yield

    agent.astream = stream
    response = client.post(
        "/stream", json={"message": "hi", "user_id": user, "model": HAIKU, "stream_tokens": False}
    )
    assert response.status_code == 200 and "[DONE]" in response.text
    assert seen == [KEY]
    assert user_key_for(HAIKU) is None

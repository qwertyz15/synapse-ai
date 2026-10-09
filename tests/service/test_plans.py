"""Plans: free accounts get a daily message allowance on chosen models; admins and unlimited don't."""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from core.settings import settings
from db.engine import async_session_scope
from db.users import get_user
from schema.models import DeepseekModelName, OpenAIModelName

FLASH = DeepseekModelName.DEEPSEEK_V4_FLASH
GPT = OpenAIModelName.GPT_5_MINI


@pytest.fixture
def plan_settings():
    with (
        patch.object(settings, "FREE_MESSAGES_PER_DAY", 2),
        patch.object(settings, "FREE_MODELS", ""),
        patch.object(settings, "ADMIN_EMAILS", "boss@x.com"),
        patch.object(settings, "DEFAULT_PLAN", "free"),
        patch.object(settings, "AVAILABLE_MODELS", {FLASH, GPT}),
        patch.object(settings, "DEFAULT_MODEL", GPT),
        patch.object(settings, "FREE_MAX_FILE_MB", 5),
        patch.object(settings, "FREE_LIBRARY_FILES", 10),
    ):
        yield


def _account(client, email="ana@x.com") -> str:
    body = {"google_sub": f"sub-{email}", "email": email, "email_verified": True}
    return client.post("/auth/sign-in", json=body).json()["id"]


def _send(client, user_id: str, model: str | None = None) -> int:
    body = {"message": "hi", "user_id": user_id, **({"model": model} if model else {})}
    return client.post("/invoke", json=body).status_code


@pytest.fixture
def replies(mock_agent):
    mock_agent.ainvoke.return_value = [("values", {"messages": [AIMessage(content="ok")]})]
    return mock_agent


def test_free_accounts_stop_at_the_daily_limit(test_client, replies, plan_settings):
    user = _account(test_client)
    assert [_send(test_client, user) for _ in range(3)] == [200, 200, 429]
    plan = test_client.get("/auth/plan", params={"user_id": user}).json()
    assert plan == {
        "plan": "free",
        "messages_today": 2,
        "daily_limit": 2,
        "models": None,
        "own_key_providers": [],
        "max_file_mb": 5,
        "library_files": 10,
    }


def test_a_new_day_starts_a_new_allowance(test_client, replies, plan_settings):
    user = _account(test_client)
    with patch("service.plans.today", return_value="2026-01-01"):
        assert [_send(test_client, user) for _ in range(3)] == [200, 200, 429]
    with patch("service.plans.today", return_value="2026-01-02"):
        assert _send(test_client, user) == 200


@pytest.mark.asyncio
async def test_admins_and_unlimited_have_no_cap_unless_one_is_set(
    test_client, replies, plan_settings
):
    boss = _account(test_client, "boss@x.com")
    friend = _account(test_client, "friend@x.com")
    async with async_session_scope() as session:
        (await get_user(session, friend)).plan = "unlimited"
    assert all(_send(test_client, u) == 200 for u in [boss, friend] for _ in range(4))
    assert test_client.get("/auth/plan", params={"user_id": boss}).json()["plan"] == "admin"

    async with async_session_scope() as session:
        (await get_user(session, friend)).daily_message_limit = 5
    assert [_send(test_client, friend) for _ in range(2)] == [200, 429]


def test_requests_without_an_account_are_not_limited(test_client, replies, plan_settings):
    assert all(_send(test_client, "anonymous-browser") == 200 for _ in range(4))
    assert test_client.get("/auth/plan", params={"user_id": "anonymous-browser"}).json() is None


def test_free_accounts_only_use_free_models(test_client, replies, plan_settings):
    user = _account(test_client)
    with patch.object(settings, "FREE_MODELS", f"{FLASH}, not-a-real-model"):
        assert test_client.get("/auth/plan", params={"user_id": user}).json()["models"] == [FLASH]
        assert _send(test_client, user, GPT) == 403
        assert _send(test_client, user) == 200
    config = replies.ainvoke.await_args.kwargs["config"]
    assert config["configurable"]["model"] == FLASH

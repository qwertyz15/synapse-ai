"""The admin endpoints: only admins, and their changes to plans, limits and blocking take effect."""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from core.settings import settings
from service import user_keys


@pytest.fixture
def setup(test_client, mock_agent):
    mock_agent.ainvoke.return_value = [("values", {"messages": [AIMessage(content="ok")]})]
    with (
        patch.object(settings, "ADMIN_EMAILS", "boss@x.com"),
        patch.object(settings, "DEFAULT_PLAN", "free"),
        patch.object(settings, "FREE_MESSAGES_PER_DAY", 3),
        patch.object(settings, "USER_KEYS_SECRET", SecretStr("k")),
        patch.object(user_keys, "verify_key", AsyncMock(return_value=True)),
    ):
        ids = {}
        for email in ["boss@x.com", "ana@x.com", "bob@x.com"]:
            body = {"google_sub": f"sub-{email}", "email": email, "email_verified": True}
            ids[email.split("@")[0]] = test_client.post("/auth/sign-in", json=body).json()["id"]
        yield test_client, ids


def _users(client, caller):
    return client.get("/admin/users", params={"user_id": caller})


def _update(client, caller, target, **change):
    return client.patch(f"/admin/users/{target}", params={"user_id": caller}, json=change)


def _send(client, user):
    return client.post("/invoke", json={"message": "hi", "user_id": user}).status_code


def test_only_admins_get_in(setup):
    client, ids = setup
    assert _users(client, ids["ana"]).status_code == 403
    assert _users(client, "anonymous-browser").status_code == 403
    assert _update(client, ids["ana"], ids["bob"], plan="unlimited").status_code == 403


def test_lists_accounts_with_usage_and_keys(setup):
    client, ids = setup
    _send(client, ids["ana"])
    client.put("/auth/keys/groq", params={"user_id": ids["ana"]}, json={"api_key": "gsk_abcdefgh"})
    users = {u["email"]: u for u in _users(client, ids["boss"]).json()["users"]}
    assert users["boss@x.com"]["plan"] == "admin" and users["boss@x.com"]["effective_limit"] is None
    assert users["ana@x.com"]["messages_today"] == 1 and users["ana@x.com"]["effective_limit"] == 3
    assert users["ana@x.com"]["own_key_providers"] == ["groq"]


def test_plan_and_limit_changes_take_effect(setup):
    client, ids = setup
    bob, boss = ids["bob"], ids["boss"]
    row = _update(client, boss, bob, plan="unlimited").json()
    assert row["plan"] == "unlimited" and row["effective_limit"] is None
    assert all(_send(client, bob) == 200 for _ in range(4))

    row = _update(client, boss, bob, daily_message_limit=5).json()
    assert row["plan"] == "unlimited" and row["effective_limit"] == 5
    assert _send(client, bob) == 200 and _send(client, bob) == 429

    row = _update(client, boss, bob, daily_message_limit=None, plan="free").json()
    assert row["daily_message_limit"] is None and row["effective_limit"] == 3
    assert _update(client, boss, bob, blocked=False).json()["effective_limit"] == 3


def test_blocking_stops_chat_uploads_and_sign_in(setup):
    client, ids = setup
    ana, boss = ids["ana"], ids["boss"]
    assert _update(client, boss, ana, blocked=True).json()["blocked"] is True
    assert _send(client, ana) == 403
    upload = client.post(
        "/rag/my-documents", params={"user_id": ana}, files=[("files", ("a.txt", b"hi"))]
    )
    assert upload.status_code == 403
    signin = client.post(
        "/auth/sign-in",
        json={"google_sub": "sub-ana@x.com", "email": "ana@x.com", "email_verified": True},
    )
    assert signin.status_code == 403 and signin.json()["code"] == "blocked"

    _update(client, boss, ana, blocked=False)
    assert _send(client, ana) == 200


def test_refuses_blocking_admins_unknown_accounts_and_bad_limits(setup):
    client, ids = setup
    assert _update(client, ids["boss"], ids["boss"], blocked=True).status_code == 400
    assert _update(client, ids["boss"], "nobody", plan="free").status_code == 404
    assert _update(client, ids["boss"], ids["ana"], daily_message_limit=-1).status_code == 422

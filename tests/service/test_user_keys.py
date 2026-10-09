"""Personal API keys: encrypted, shown only by their last characters, and checked with the provider."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from core.settings import settings
from db.engine import async_session_scope
from db.models import UserApiKey
from service import app, user_keys

KEY = "sk-test-abcdefgh1234"


@pytest.fixture
def client():
    with patch.object(settings, "USER_KEYS_SECRET", SecretStr("keys-secret")):
        yield TestClient(app)


def _account(client, email="ana@x.com") -> str:
    body = {"google_sub": f"sub-{email}", "email": email, "email_verified": True}
    return client.post("/auth/sign-in", json=body).json()["id"]


def _save(client, user, provider="openai", key=KEY, verified=True):
    with patch.object(user_keys, "verify_key", AsyncMock(return_value=verified)):
        return client.put(f"/auth/keys/{provider}", params={"user_id": user}, json={"api_key": key})


def test_off_without_a_secret():
    with patch.object(settings, "USER_KEYS_SECRET", None):
        client = TestClient(app)
        assert client.get("/auth/keys", params={"user_id": "u"}).json()["enabled"] is False
        assert _save(client, _account(client)).status_code == 503


@pytest.mark.asyncio
async def test_saves_encrypted_and_shows_only_the_end(client):
    user = _account(client)
    saved = _save(client, user).json()
    assert saved["provider"] == "openai" and saved["last4"] == "1234" and saved["verified"] is True
    listing = client.get("/auth/keys", params={"user_id": user}).json()
    assert listing["enabled"] is True and "anthropic" in listing["providers"]
    assert [k["last4"] for k in listing["keys"]] == ["1234"]
    assert KEY not in str(listing)

    async with async_session_scope() as session:
        row = (await session.scalars(select(UserApiKey))).one()
    assert KEY not in row.encrypted_key
    assert await user_keys.load_user_keys(user) == {"openai": KEY}


def test_refuses_anonymous_users_bad_keys_and_unknown_providers(client):
    assert _save(client, "anonymous-browser").status_code == 403
    user = _account(client)
    assert _save(client, user, verified=False).status_code == 400
    assert _save(client, user, key="sk has spaces").status_code == 400
    assert _save(client, user, provider="azure").status_code == 404
    assert client.get("/auth/keys", params={"user_id": user}).json()["keys"] == []


def test_keeps_keys_the_provider_couldnt_check(client):
    user = _account(client)
    assert _save(client, user, verified=None).json()["verified"] is False


def test_replace_and_remove_are_per_account(client):
    ana, bob = _account(client), _account(client, "bob@x.com")
    _save(client, ana)
    _save(client, ana, key="sk-test-replaced-9999")
    assert [
        k["last4"] for k in client.get("/auth/keys", params={"user_id": ana}).json()["keys"]
    ] == ["9999"]
    assert client.get("/auth/keys", params={"user_id": bob}).json()["keys"] == []
    client.delete("/auth/keys/openai", params={"user_id": bob})
    assert len(client.get("/auth/keys", params={"user_id": ana}).json()["keys"]) == 1
    assert client.delete("/auth/keys/openai", params={"user_id": ana}).json()["keys"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"), [(200, True), (401, False), (403, False), (500, None)]
)
async def test_verify_key_asks_the_provider(status, expected):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"] = str(request.url), request.headers
        return httpx.Response(status)

    real = httpx.AsyncClient
    with patch.object(
        user_keys.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    ):
        assert await user_keys.verify_key("anthropic", KEY) is expected
    assert seen["url"] == "https://api.anthropic.com/v1/models"
    assert seen["headers"]["x-api-key"] == KEY

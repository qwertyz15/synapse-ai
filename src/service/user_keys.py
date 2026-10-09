"""API keys users save for themselves, so their chats on that provider run on their own account.

Keys are encrypted with AES-GCM under USER_KEYS_SECRET and never returned; the API only shows the
last four characters. Only signed-in accounts can save keys.
"""

import base64
import hashlib
import logging
import os

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select

from core import settings
from core.llm import PROVIDER_NAMES, USER_KEY_PROVIDERS
from db.engine import async_session_scope
from db.models import UserApiKey, utcnow
from db.users import get_user
from schema import UserKey, UserKeyInput, UserKeys

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFY_TIMEOUT_S = 10

# One cheap, free request per provider that fails with 401/403 for a bad key.
_CHECKS: dict[str, tuple[str, str, str]] = {
    "openai": ("https://api.openai.com/v1/models", "Authorization", "Bearer {}"),
    "anthropic": ("https://api.anthropic.com/v1/models", "x-api-key", "{}"),
    "deepseek": ("https://api.deepseek.com/models", "Authorization", "Bearer {}"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key", "{}"),
    "groq": ("https://api.groq.com/openai/v1/models", "Authorization", "Bearer {}"),
    "openrouter": ("https://openrouter.ai/api/v1/key", "Authorization", "Bearer {}"),
}


def _cipher() -> AESGCM | None:
    if not settings.USER_KEYS_SECRET:
        return None
    secret = settings.USER_KEYS_SECRET.get_secret_value().encode()
    return AESGCM(hashlib.sha256(secret).digest())


def encrypt(plain: str, cipher: AESGCM) -> str:
    nonce = os.urandom(12)
    return base64.urlsafe_b64encode(nonce + cipher.encrypt(nonce, plain.encode(), None)).decode()


def decrypt(sealed: str, cipher: AESGCM) -> str:
    raw = base64.urlsafe_b64decode(sealed)
    return cipher.decrypt(raw[:12], raw[12:], None).decode()


async def verify_key(provider: str, api_key: str) -> bool | None:
    """True if the provider accepts the key, False if it rejects it, None if it couldn't be asked."""
    url, header, template = _CHECKS[provider]
    headers = {header: template.format(api_key)}
    if provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    try:
        async with httpx.AsyncClient(timeout=VERIFY_TIMEOUT_S) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        logger.warning(f"Couldn't verify a {provider} key: {type(e).__name__}")
        return None
    if response.status_code in (401, 403):
        return False
    return True if response.is_success else None


async def load_user_keys(user_id: str | None) -> dict[str, str]:
    """The account's saved keys by provider, decrypted for one run; empty when there are none."""
    cipher = _cipher()
    if not user_id or cipher is None:
        return {}
    async with async_session_scope() as session:
        rows = (
            await session.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id))
        ).all()
    keys: dict[str, str] = {}
    for row in rows:
        try:
            keys[row.provider] = decrypt(row.encrypted_key, cipher)
        except Exception:
            logger.warning(f"Couldn't decrypt the {row.provider} key of account {user_id}")
    return keys


def _shown(row: UserApiKey, verified: bool = True) -> UserKey:
    return UserKey(
        provider=row.provider, last4=row.last4, added_at=row.created_at, verified=verified
    )


async def _require_account(user_id: str) -> None:
    async with async_session_scope() as session:
        if await get_user(session, user_id) is None:
            raise HTTPException(status_code=403, detail="Sign in to save your own API keys.")


def _require_provider(provider: str) -> None:
    if provider not in USER_KEY_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")


@router.get("/keys")
async def list_keys(user_id: str) -> UserKeys:
    """The account's saved keys (last four characters only) and the providers keys work for."""
    async with async_session_scope() as session:
        rows = (
            await session.scalars(select(UserApiKey).where(UserApiKey.user_id == user_id))
        ).all()
        keys = [_shown(row) for row in rows]
    return UserKeys(enabled=_cipher() is not None, providers=list(USER_KEY_PROVIDERS), keys=keys)


@router.put("/keys/{provider}")
async def save_key(provider: str, user_id: str, body: UserKeyInput) -> UserKey:
    """Check the key with the provider, then save it encrypted, replacing an earlier one."""
    _require_provider(provider)
    cipher = _cipher()
    if cipher is None:
        raise HTTPException(status_code=503, detail="This server doesn't accept personal API keys.")
    await _require_account(user_id)
    api_key = body.api_key.strip()
    if any(c.isspace() for c in api_key):
        raise HTTPException(status_code=400, detail="That doesn't look like an API key.")
    verified = await verify_key(provider, api_key)
    if verified is False:
        raise HTTPException(
            status_code=400,
            detail=f"{PROVIDER_NAMES[provider]} rejected this key. Check it and try again.",
        )
    async with async_session_scope() as session:
        row = await session.get(UserApiKey, (user_id, provider))
        if row is None:
            row = UserApiKey(user_id=user_id, provider=provider)
            session.add(row)
        row.encrypted_key, row.last4, row.created_at = (
            encrypt(api_key, cipher),
            api_key[-4:],
            utcnow(),
        )
        return _shown(row, verified=verified is True)


@router.delete("/keys/{provider}")
async def delete_key(provider: str, user_id: str) -> UserKeys:
    """Remove the account's key for a provider."""
    _require_provider(provider)
    async with async_session_scope() as session:
        await session.execute(
            delete(UserApiKey).where(UserApiKey.user_id == user_id, UserApiKey.provider == provider)
        )
    return await list_keys(user_id)

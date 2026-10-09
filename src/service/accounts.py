"""Sign-in for accounts: who may join (ADMIN_EMAILS, SIGNUPS, ALLOWED_EMAILS) and claiming an
anonymous browser's chats and files. The web UI does the Google OAuth and calls this server-side."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from core import settings
from db.engine import async_session_scope
from db.models import User
from db.users import find_google_user, move_anonymous_rows, save_google_user
from ingestion.attachments import open_attachment_store
from ingestion.index import reassign_user
from ingestion.user_library import open_user_library
from schema import Account, GoogleSignIn
from service.rag import ingestion_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def is_admin(email: str) -> bool:
    return email.lower() in settings.admin_emails()


def may_join(email: str) -> bool:
    """Whether a new account may be created for this (verified) email."""
    email = email.lower()
    if is_admin(email) or settings.SIGNUPS == "open":
        return True
    if settings.SIGNUPS == "closed":
        return False
    allowed = settings.allowed_emails()
    return email in allowed or f"@{email.rsplit('@', 1)[-1]}" in allowed


def account(user: User) -> Account:
    return Account(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        is_admin=is_admin(user.email),
    )


async def _claim_anonymous(from_user: str, to_user: str) -> None:
    async with async_session_scope() as session:
        kept = await move_anonymous_rows(session, from_user, to_user)
    if not Path(settings.CHROMA_DB_PATH).is_dir():
        return
    async with ingestion_lock:
        for store, keep in (
            (open_attachment_store(settings.CHROMA_DB_PATH), set()),
            (open_user_library(settings.CHROMA_DB_PATH), kept),
        ):
            await run_in_threadpool(reassign_user, store, from_user, to_user, keep)


@router.post("/sign-in")
async def sign_in(profile: GoogleSignIn) -> Account:
    """Create or update the account for a Google profile and return it.

    Refused with 403 when sign-ups don't allow this email. The browser's anonymous chats and
    files, if any, move to the account.
    """
    if not profile.email_verified:
        raise HTTPException(status_code=403, detail="Your Google email address isn't verified.")
    email = profile.email.strip().lower()
    async with async_session_scope() as session:
        existing = await find_google_user(session, profile.google_sub, email)
        if existing is None and not may_join(email):
            raise HTTPException(
                status_code=403, detail="This app is invite-only, and your email isn't on the list."
            )
        user = await save_google_user(
            session, existing, profile.google_sub, email, profile.name, profile.avatar_url
        )
        result = account(user)
    if profile.anonymous_user_id and profile.anonymous_user_id != result.id:
        try:
            await _claim_anonymous(profile.anonymous_user_id, result.id)
        except Exception:
            logger.exception("Couldn't move anonymous chats to account %s", result.id)
    return result

"""Queries for signed-in accounts and for handing an anonymous browser's data to an account."""

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, ChatAttachment, IngestionJob, User, UserDocument, utcnow


async def find_google_user(session: AsyncSession, google_sub: str, email: str) -> User | None:
    """The account for this Google id, or (e.g. after a Google account was recreated) its email."""
    user = await session.scalar(select(User).where(User.google_sub == google_sub))
    return user or await session.scalar(select(User).where(User.email == email))


async def save_google_user(
    session: AsyncSession,
    existing: User | None,
    google_sub: str,
    email: str,
    name: str | None,
    avatar_url: str | None,
    plan: str = "free",
) -> User:
    """Create the account on first sign-in (on `plan`), or refresh its profile and last login."""
    user = existing or User(id=str(uuid4()), google_sub=google_sub, email=email, plan=plan)
    if existing is None:
        session.add(user)
    user.google_sub, user.email = google_sub, email
    user.name, user.avatar_url, user.last_login_at = name, avatar_url, utcnow()
    return user


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


async def move_anonymous_rows(session: AsyncSession, from_user: str, to_user: str) -> set[str]:
    """Give an anonymous browser's chats, attachments and library files to an account.

    Returns the library file names that were left behind because the account already has a file
    with that name.
    """
    await session.execute(update(Chat).where(Chat.user_id == from_user).values(user_id=to_user))
    await session.execute(
        update(IngestionJob).where(IngestionJob.user_id == from_user).values(user_id=to_user)
    )
    await session.execute(
        update(ChatAttachment).where(ChatAttachment.user_id == from_user).values(user_id=to_user)
    )
    taken = set(
        await session.scalars(select(UserDocument.name).where(UserDocument.user_id == to_user))
    )
    await session.execute(
        update(UserDocument)
        .where(UserDocument.user_id == from_user, UserDocument.name.not_in(taken))
        .values(user_id=to_user)
    )
    return taken

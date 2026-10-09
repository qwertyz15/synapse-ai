"""Queries for chats and their attachment rows (async, used by the service)."""

from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, ChatAttachment, utcnow

TITLE_MAX_LENGTH = 60


class ChatAccessError(Exception):
    """The thread exists but belongs to another user or agent."""


def make_title(message: str) -> str | None:
    title = " ".join(message.split())
    return title[:TITLE_MAX_LENGTH] or None


async def claim_chat(
    session: AsyncSession,
    thread_id: str,
    user_id: str | None,
    agent_id: str,
    message: str,
    model: str | None = None,
) -> Chat:
    """Create the chat on its first message, or bump `updated_at`; refuse someone else's chat.

    A caller without a user id continues the chat as its owner, as the API allowed before chats
    were tracked; a caller with a different user id is refused.
    """
    chat = await session.get(Chat, thread_id)
    if chat is None:
        chat = Chat(
            thread_id=thread_id,
            user_id=user_id or str(uuid4()),
            agent_id=agent_id,
            title=make_title(message),
        )
        try:
            async with session.begin_nested():
                session.add(chat)
        except IntegrityError:
            # Created concurrently by another request for the same thread.
            chat = await session.get(Chat, thread_id, populate_existing=True)
            if chat is None:
                raise
    if (user_id is not None and chat.user_id != user_id) or chat.agent_id != agent_id:
        raise ChatAccessError(thread_id)
    chat.updated_at = utcnow()
    if model is not None:
        chat.model = model
    return chat


async def get_chat(session: AsyncSession, thread_id: str) -> Chat | None:
    return await session.get(Chat, thread_id)


async def list_chats(
    session: AsyncSession, user_id: str, agent_id: str | None = None, limit: int = 20
) -> Sequence[Chat]:
    query = select(Chat).where(Chat.user_id == user_id)
    if agent_id is not None:
        query = query.where(Chat.agent_id == agent_id)
    query = query.order_by(Chat.updated_at.desc()).limit(limit)
    return (await session.scalars(query)).all()


async def replace_title(
    session: AsyncSession, thread_id: str, expected: str | None, title: str
) -> bool:
    """Set the title only if it's still `expected`, so a title set meanwhile is kept."""
    chat = await session.get(Chat, thread_id)
    if chat is None or chat.title != expected:
        return False
    chat.title = title
    return True


async def rename_chat(
    session: AsyncSession, thread_id: str, user_id: str, agent_id: str, title: str
) -> Chat | None:
    """Set a chat's title; None if the chat doesn't exist or belongs to someone else."""
    chat = await session.get(Chat, thread_id)
    if chat is None or (chat.user_id, chat.agent_id) != (user_id, agent_id):
        return None
    chat.title = title
    return chat


async def delete_chat(session: AsyncSession, thread_id: str) -> None:
    await session.execute(delete(ChatAttachment).where(ChatAttachment.thread_id == thread_id))
    await session.execute(delete(Chat).where(Chat.thread_id == thread_id))


async def upsert_attachment(
    session: AsyncSession, thread_id: str, user_id: str, name: str, file_type: str, chunk_count: int
) -> None:
    row = await session.scalar(
        select(ChatAttachment).where(
            ChatAttachment.thread_id == thread_id,
            ChatAttachment.user_id == user_id,
            ChatAttachment.name == name,
        )
    )
    if row is None:
        session.add(
            ChatAttachment(
                thread_id=thread_id,
                user_id=user_id,
                name=name,
                file_type=file_type,
                chunk_count=chunk_count,
            )
        )
    else:
        row.file_type, row.chunk_count, row.created_at = file_type, chunk_count, utcnow()


async def list_attachments(
    session: AsyncSession, thread_id: str, user_id: str
) -> Sequence[ChatAttachment]:
    query = (
        select(ChatAttachment)
        .where(ChatAttachment.thread_id == thread_id, ChatAttachment.user_id == user_id)
        .order_by(ChatAttachment.name)
    )
    return (await session.scalars(query)).all()


async def delete_attachment(session: AsyncSession, thread_id: str, user_id: str, name: str) -> bool:
    result: CursorResult = await session.execute(  # type: ignore[assignment]
        delete(ChatAttachment).where(
            ChatAttachment.thread_id == thread_id,
            ChatAttachment.user_id == user_id,
            ChatAttachment.name == name,
        )
    )
    return bool(result.rowcount)

"""Queries for files in each user's private library (async, used by the service)."""

from collections.abc import Sequence

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import UserDocument, utcnow


async def upsert_user_document(
    session: AsyncSession, user_id: str, name: str, file_type: str, chunk_count: int
) -> bool:
    """Record a file; returns True when it replaced an earlier file with the same name."""
    row = await session.scalar(
        select(UserDocument).where(UserDocument.user_id == user_id, UserDocument.name == name)
    )
    if row is None:
        session.add(
            UserDocument(user_id=user_id, name=name, file_type=file_type, chunk_count=chunk_count)
        )
        return False
    row.file_type, row.chunk_count, row.created_at = file_type, chunk_count, utcnow()
    return True


async def list_user_documents(session: AsyncSession, user_id: str) -> Sequence[UserDocument]:
    result = await session.scalars(
        select(UserDocument).where(UserDocument.user_id == user_id).order_by(UserDocument.name)
    )
    return result.all()


async def delete_user_document(session: AsyncSession, user_id: str, name: str) -> bool:
    result: CursorResult = await session.execute(  # type: ignore[assignment]
        delete(UserDocument).where(UserDocument.user_id == user_id, UserDocument.name == name)
    )
    return result.rowcount > 0

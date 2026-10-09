"""Per-account daily message counts."""

from datetime import UTC, datetime

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DailyUsage


def today() -> str:
    return datetime.now(UTC).date().isoformat()


async def messages_on(session: AsyncSession, user_id: str, day: str) -> int:
    count = await session.scalar(
        select(DailyUsage.messages).where(DailyUsage.user_id == user_id, DailyUsage.day == day)
    )
    return count or 0


async def use_message(session: AsyncSession, user_id: str, day: str, limit: int | None) -> bool:
    """Count one message unless that would pass `limit`; returns whether it was allowed.

    The check and the increment are one UPDATE, so simultaneous requests can't overshoot.
    """
    if await session.get(DailyUsage, (user_id, day)) is None:
        try:
            async with session.begin_nested():
                session.add(DailyUsage(user_id=user_id, day=day, messages=0))
        except IntegrityError:
            pass
    statement = (
        update(DailyUsage)
        .where(DailyUsage.user_id == user_id, DailyUsage.day == day)
        .values(messages=DailyUsage.messages + 1)
    )
    if limit is not None:
        statement = statement.where(DailyUsage.messages < limit)
    result: CursorResult = await session.execute(statement)  # type: ignore[assignment]
    return result.rowcount > 0

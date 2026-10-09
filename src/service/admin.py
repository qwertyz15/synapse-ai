"""Admin endpoints: see every account and change its plan, daily limit or blocked status.

The caller (`user_id`, set by the web proxy) must be an admin per ADMIN_EMAILS, checked on every
request so a change to that list takes effect at once.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from db.engine import async_session_scope
from db.models import DailyUsage, User, UserApiKey
from db.usage import today
from db.users import get_user
from schema import AdminUser, AdminUsers, AdminUserUpdate
from service.accounts import is_admin
from service.plans import daily_limit, plan_of

router = APIRouter(prefix="/admin", tags=["admin"])


async def _require_admin(session, user_id: str) -> User:
    user = await get_user(session, user_id)
    if user is None or not is_admin(user.email):
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


def _row(user: User, messages_today: int, providers: list[str]) -> AdminUser:
    return AdminUser(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        plan=plan_of(user),
        daily_message_limit=user.daily_message_limit,
        effective_limit=daily_limit(user),
        messages_today=messages_today,
        own_key_providers=providers,
        blocked=user.blocked,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def _rows(session, users: list[User]) -> list[AdminUser]:
    ids = [u.id for u in users]
    usage = dict(
        (
            await session.execute(
                select(DailyUsage.user_id, DailyUsage.messages).where(
                    DailyUsage.day == today(), DailyUsage.user_id.in_(ids)
                )
            )
        ).all()
    )
    providers: dict[str, list[str]] = {}
    for uid, provider in (
        await session.execute(
            select(UserApiKey.user_id, UserApiKey.provider)
            .where(UserApiKey.user_id.in_(ids))
            .order_by(UserApiKey.provider)
        )
    ).all():
        providers.setdefault(uid, []).append(provider)
    return [_row(u, usage.get(u.id, 0), providers.get(u.id, [])) for u in users]


@router.get("/users")
async def list_users(user_id: str) -> AdminUsers:
    """Every account, most recently active first, with its plan and today's usage."""
    async with async_session_scope() as session:
        await _require_admin(session, user_id)
        users = list(await session.scalars(select(User).order_by(User.last_login_at.desc())))
        return AdminUsers(users=await _rows(session, users))


@router.patch("/users/{target_id}")
async def update_user(target_id: str, user_id: str, change: AdminUserUpdate) -> AdminUser:
    """Change an account's plan, its own daily limit (null clears it) or whether it's blocked."""
    async with async_session_scope() as session:
        admin = await _require_admin(session, user_id)
        user = await get_user(session, target_id)
        if user is None:
            raise HTTPException(status_code=404, detail="No such account.")
        if change.blocked and (user.id == admin.id or is_admin(user.email)):
            raise HTTPException(
                status_code=400,
                detail="Admins can't be blocked; remove them from ADMIN_EMAILS first.",
            )
        if change.plan is not None:
            user.plan = change.plan
        if "daily_message_limit" in change.model_fields_set:
            user.daily_message_limit = change.daily_message_limit
        if change.blocked is not None:
            user.blocked = change.blocked
        return (await _rows(session, [user]))[0]

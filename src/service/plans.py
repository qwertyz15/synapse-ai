"""What each account may do with the server's model keys: its plan, daily messages and models.

Admins (ADMIN_EMAILS) and `unlimited` accounts have no daily cap unless an admin set one for them;
`free` accounts get FREE_MESSAGES_PER_DAY messages a day on FREE_MODELS. Requests without an account
(sign-in off, or API callers) aren't limited here.
"""

from collections.abc import Collection
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from core import settings
from core.llm import models_for, provider_of
from db.engine import async_session_scope
from db.models import User, UserApiKey
from db.usage import messages_on, today, use_message
from db.users import get_user
from schema import PlanInfo, UserInput
from service.accounts import BLOCKED, is_admin, is_blocked

router = APIRouter(prefix="/auth", tags=["auth"])


def plan_of(user: User) -> Literal["admin", "unlimited", "free"]:
    if is_admin(user.email):
        return "admin"
    return "unlimited" if user.plan == "unlimited" else "free"


def daily_limit(user: User) -> int | None:
    if user.daily_message_limit is not None:
        return user.daily_message_limit
    return settings.FREE_MESSAGES_PER_DAY if plan_of(user) == "free" else None


def allowed_models(user: User) -> list[str] | None:
    """Models this account may pick, in FREE_MODELS order; None means any available model."""
    if plan_of(user) != "free" or not settings.free_models():
        return None
    available = {str(m) for m in settings.AVAILABLE_MODELS}
    return [m for m in settings.free_models() if m in available]


def max_file_mb(user: User | None) -> int | None:
    return settings.FREE_MAX_FILE_MB if user and plan_of(user) == "free" else None


def library_files(user: User | None) -> int | None:
    return settings.FREE_LIBRARY_FILES if user and plan_of(user) == "free" else None


async def upload_limits(user_id: str) -> tuple[int | None, int | None]:
    """(largest file in MB, library file cap) for this user; None means no plan limit."""
    async with async_session_scope() as session:
        user = await get_user(session, user_id)
    if user is not None and is_blocked(user):
        raise HTTPException(status_code=403, detail=BLOCKED)
    return max_file_mb(user), library_files(user)


def with_own_keys(models: list[str] | None, own_key_providers: list[str]) -> list[str] | None:
    """Add the models the user's own keys unlock; None (every server model) stays None without keys."""
    if not own_key_providers:
        return models
    base = models if models is not None else sorted(str(m) for m in settings.AVAILABLE_MODELS)
    extra = [m for p in own_key_providers for m in models_for(p)]
    return list(dict.fromkeys([*base, *extra]))


async def plan_info(user_id: str) -> PlanInfo | None:
    async with async_session_scope() as session:
        user = await get_user(session, user_id)
        if user is None:
            return None
        own = list(
            await session.scalars(
                select(UserApiKey.provider)
                .where(UserApiKey.user_id == user_id)
                .order_by(UserApiKey.provider)
            )
        )
        return PlanInfo(
            plan=plan_of(user),
            messages_today=await messages_on(session, user_id, today()),
            daily_limit=daily_limit(user),
            models=with_own_keys(allowed_models(user), own),
            own_key_providers=own,
            max_file_mb=max_file_mb(user),
            library_files=library_files(user),
        )


async def charge_message(user_input: UserInput, own_key_providers: Collection[str] = ()) -> None:
    """Check the account may send this message with this model, and count it.

    Picks the plan's first model when none was chosen and the default isn't allowed. Raises 403 for
    a model outside the plan and 429 once the day's messages are used up. A message to a provider
    the user has their own key for is free: not counted, capped or limited to the plan's models.
    """
    if not user_input.user_id:
        return
    async with async_session_scope() as session:
        user = await get_user(session, user_id=user_input.user_id)
        if user is None:
            return
        if is_blocked(user):
            raise HTTPException(status_code=403, detail=BLOCKED)
        chosen = str(user_input.model or settings.DEFAULT_MODEL)
        if provider_of(chosen) in own_key_providers:
            return
        models = allowed_models(user)
        if models is not None:
            if not models:
                raise HTTPException(status_code=403, detail="No models are available on your plan.")
            if user_input.model is None and str(settings.DEFAULT_MODEL) not in models:
                user_input.model = models[0]  # type: ignore[assignment]
            elif user_input.model is not None and str(user_input.model) not in models:
                raise HTTPException(
                    status_code=403,
                    detail=f"{user_input.model} isn't included in your plan. Pick another model.",
                )
        limit = daily_limit(user)
        if not await use_message(session, user.id, today(), limit):
            raise HTTPException(
                status_code=429,
                detail=f"You've used all {limit} messages for today. They reset at midnight UTC.",
            )


@router.get("/plan")
async def get_plan(user_id: str) -> PlanInfo | None:
    """The account's plan and today's usage; null when `user_id` isn't an account."""
    return await plan_info(user_id)

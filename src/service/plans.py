"""What each account may do with the server's model keys: its plan, daily messages and models.

Admins (ADMIN_EMAILS) and `unlimited` accounts have no daily cap unless an admin set one for them;
`free` accounts get FREE_MESSAGES_PER_DAY messages a day on FREE_MODELS. Requests without an account
(sign-in off, or API callers) aren't limited here.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException

from core import settings
from db.engine import async_session_scope
from db.models import User
from db.usage import messages_on, today, use_message
from db.users import get_user
from schema import PlanInfo, UserInput
from service.accounts import is_admin

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


async def plan_info(user_id: str) -> PlanInfo | None:
    async with async_session_scope() as session:
        user = await get_user(session, user_id)
        if user is None:
            return None
        return PlanInfo(
            plan=plan_of(user),
            messages_today=await messages_on(session, user_id, today()),
            daily_limit=daily_limit(user),
            models=allowed_models(user),
        )


async def charge_message(user_input: UserInput) -> None:
    """Check the account may send this message with this model, and count it.

    Picks the plan's first model when none was chosen and the default isn't allowed. Raises 403 for
    a model outside the plan and 429 once the day's messages are used up.
    """
    if not user_input.user_id:
        return
    async with async_session_scope() as session:
        user = await get_user(session, user_id=user_input.user_id)
        if user is None:
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

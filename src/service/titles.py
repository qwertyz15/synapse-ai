"""ChatGPT-style chat titles: after a chat's first message, the chat's model names it in a few words.

Runs in the background so replies aren't delayed. Until it finishes (or if it fails), the chat keeps
the title made from its first message, and a title the user has set in the meantime is never replaced.
"""

import asyncio
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from core import get_model, settings
from db.chats import replace_title
from db.engine import async_session_scope
from schema.models import AllModelEnum, FakeModelName
from service.utils import convert_message_content_to_string

logger = logging.getLogger(__name__)

TIMEOUT_S = 20
MAX_LENGTH = 60
PROMPT = (
    "Write a short title, 2 to 6 words, for a conversation that starts with the user's message "
    "below. Use the message's language. Reply with the title only: no quotes, no trailing "
    "punctuation, no explanation."
)

_tasks: set[asyncio.Task] = set()


def clean_title(text: str) -> str | None:
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    line = re.sub(r"^(title|chat title)\s*:\s*", "", line, flags=re.IGNORECASE)
    line = line.strip(" \t\"'`*#").rstrip(".!?;:,")
    if len(line) > MAX_LENGTH:
        line = line[:MAX_LENGTH].rsplit(" ", 1)[0]
    return line or None


async def generate_title(message: str, model_name: AllModelEnum) -> str | None:
    model = get_model(model_name)
    response = await asyncio.wait_for(
        model.ainvoke([SystemMessage(PROMPT), HumanMessage(message[:2000])]), TIMEOUT_S
    )
    return clean_title(convert_message_content_to_string(response.content))


async def _name_chat(thread_id: str, placeholder: str | None, message: str, model_name) -> None:
    try:
        title = await generate_title(message, model_name)
        if title:
            async with async_session_scope() as session:
                await replace_title(session, thread_id, placeholder, title)
    except Exception as e:
        logger.warning(f"Couldn't generate a title for chat {thread_id}: {type(e).__name__}: {e}")


def name_chat_later(
    thread_id: str, placeholder: str | None, message: str, model_name: AllModelEnum | None
) -> None:
    """Start naming a new chat in the background, unless titles are off or the model is fake."""
    model_name = model_name or settings.DEFAULT_MODEL
    if not settings.GENERATE_CHAT_TITLES or not message.strip() or model_name in FakeModelName:
        return
    task = asyncio.create_task(_name_chat(thread_id, placeholder, message, model_name))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

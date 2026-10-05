"""Thread ownership from the checkpointer, for threads the chats table doesn't know yet."""

from typing import Any

from langchain_core.runnables import RunnableConfig


async def thread_owner(checkpointer: Any, thread_id: str) -> tuple[str | None, str | None] | None:
    """(user_id, agent_id) recorded on a thread's latest checkpoint, or None if it has none."""
    tip = await checkpointer.aget_tuple(RunnableConfig(configurable={"thread_id": thread_id}))
    if tip is None:
        return None
    return tip.metadata.get("user_id"), tip.metadata.get("agent_id")

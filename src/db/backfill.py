"""One-time imports that fill the app tables from data created before they existed.

Each step runs once (tracked in `app_meta`) and only inserts rows that are missing, so it is safe to
run on every startup.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select

from core import settings
from db.chats import make_title
from db.engine import async_session_scope
from db.models import AppMeta, Chat, ChatAttachment, utcnow

logger = logging.getLogger(__name__)

CHATS_FLAG = "backfill.chats"
ATTACHMENTS_FLAG = "backfill.attachments"
PAGE_SIZE = 500
MAX_ROWS = 100_000


def _parse_ts(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return utcnow()


async def _done(flag: str) -> bool:
    async with async_session_scope() as session:
        return await session.get(AppMeta, flag) is not None


async def _mark(flag: str) -> None:
    async with async_session_scope() as session:
        await session.merge(AppMeta(key=flag, value=utcnow().isoformat()))


async def backfill_chats(checkpointer: Any) -> int:
    """Create a `chats` row for every thread the checkpointer already has."""
    # Imported here: the service package imports this module at startup.
    from service.utils import convert_message_content_to_string, messages_from_checkpoint

    if await _done(CHATS_FLAG):
        return 0
    seen: set[str] = set()
    created = 0
    before = None
    scanned = 0
    while scanned < MAX_ROWS:
        page = [
            c
            async for c in checkpointer.alist(
                None, filter={"step": -1}, before=before, limit=PAGE_SIZE
            )
        ]
        if not page:
            break
        scanned += len(page)
        async with async_session_scope() as session:
            for head in page:
                thread_id = head.config["configurable"]["thread_id"]
                user_id, agent_id = head.metadata.get("user_id"), head.metadata.get("agent_id")
                if thread_id in seen or not user_id or not agent_id:
                    continue
                seen.add(thread_id)
                if await session.get(Chat, thread_id) is not None:
                    continue
                tip = await checkpointer.aget_tuple(
                    RunnableConfig(configurable={"thread_id": thread_id})
                )
                if tip is None:
                    continue
                messages = messages_from_checkpoint(tip.checkpoint)
                first = next((m for m in messages if isinstance(m, HumanMessage)), None)
                session.add(
                    Chat(
                        thread_id=thread_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        title=make_title(convert_message_content_to_string(first.content))
                        if first
                        else None,
                        created_at=_parse_ts(head.checkpoint.get("ts")),
                        updated_at=_parse_ts(tip.checkpoint.get("ts")),
                    )
                )
                created += 1
        if len(page) < PAGE_SIZE:
            break
        before = RunnableConfig(
            configurable={"checkpoint_id": page[-1].config["configurable"]["checkpoint_id"]}
        )
    await _mark(CHATS_FLAG)
    return created


async def backfill_attachments() -> int:
    """Create `chat_attachments` rows for files already indexed in the Chroma collection."""
    if await _done(ATTACHMENTS_FLAG):
        return 0
    created = 0
    if Path(settings.CHROMA_DB_PATH).is_dir():
        from ingestion.attachments import ATTACHMENTS_COLLECTION
        from ingestion.index import chroma_client

        client = chroma_client(settings.CHROMA_DB_PATH)
        if ATTACHMENTS_COLLECTION in {c.name for c in client.list_collections()}:
            metadatas = (
                client.get_collection(ATTACHMENTS_COLLECTION).get(include=["metadatas"])[
                    "metadatas"
                ]
                or []
            )
            files: dict[tuple[str, str, str], dict[str, Any]] = {}
            for meta in metadatas:
                key = (str(meta["thread_id"]), str(meta["user_id"]), str(meta["source"]))
                entry = files.setdefault(key, {"meta": meta, "chunks": 0})
                entry["chunks"] += 1
            async with async_session_scope() as session:
                for (thread_id, user_id, name), entry in files.items():
                    exists = await session.scalar(
                        select(ChatAttachment.id).where(
                            ChatAttachment.thread_id == thread_id,
                            ChatAttachment.user_id == user_id,
                            ChatAttachment.name == name,
                        )
                    )
                    if exists:
                        continue
                    session.add(
                        ChatAttachment(
                            thread_id=thread_id,
                            user_id=user_id,
                            name=name,
                            file_type=str(entry["meta"].get("file_type", "")),
                            chunk_count=entry["chunks"],
                            created_at=_parse_ts(entry["meta"].get("ingested_at")),
                        )
                    )
                    created += 1
    await _mark(ATTACHMENTS_FLAG)
    return created


async def run_backfills(checkpointer: Any) -> None:
    for name, step in (
        ("chats", lambda: backfill_chats(checkpointer)),
        ("chat attachments", backfill_attachments),
    ):
        try:
            created = await step()
            if created:
                logger.info(f"Imported {created} existing {name} into the app database")
        except Exception:
            logger.exception(f"Importing existing {name} failed; will retry on next startup")

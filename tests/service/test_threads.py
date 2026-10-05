"""Unit tests for importing pre-existing chats into the chats table, against a fake checkpointer.

Covers what a real checkpointer can't be made to do on demand: the page and row caps (which
need more checkpoints than it's worth seeding), rows without owner metadata and a missing
timestamp. Filtering, ordering and titles against real LangGraph data are tested in
test_threads_sqlite.py.
"""

from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from db import backfill
from db.chats import list_chats
from db.engine import async_session_scope


class FakeCheckpointTuple:
    def __init__(self, thread_id: str, checkpoint_id: str, checkpoint: dict, metadata: dict):
        self.config = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
        self.checkpoint = checkpoint
        self.metadata = metadata


class FakeCheckpointer:
    """A checkpointer with the semantics the chats backfill relies on.

    Checkpoints are globally ordered by checkpoint_id, `alist` applies the metadata
    filter as exact matches, and each thread's first checkpoint is written at step -1
    the way LangGraph writes an input checkpoint.
    """

    def __init__(self):
        self.rows: list[FakeCheckpointTuple] = []
        self.alist_filters: list[dict | None] = []
        self._next_id = 0

    def _checkpoint_id(self) -> str:
        self._next_id += 1
        return f"cp-{self._next_id:06d}"

    def add_thread(
        self,
        thread_id: str,
        user_id: str = "user-123",
        agent_id: str = "research-assistant",
        turns: int = 1,
        title: str = "Hello",
        subgraph_heads: int = 0,
        tip_ts: str | None = "2024-07-31T20:14:19.804150+00:00",
    ) -> None:
        def add(step: int, channel_values: dict, ts: str | None) -> None:
            self.rows.append(
                FakeCheckpointTuple(
                    thread_id,
                    self._checkpoint_id(),
                    {"ts": ts, "channel_values": channel_values},
                    {"step": step, "user_id": user_id, "agent_id": agent_id},
                )
            )

        add(-1, {"__start__": {"messages": [HumanMessage(content=title)]}}, "2024-01-01T00:00:00Z")
        # Subgraph runs write their own head, inheriting the parent run's metadata.
        for _ in range(subgraph_heads):
            add(-1, {"__start__": {}}, "2024-01-01T00:00:00Z")

        messages: list = []
        for turn in range(turns):
            messages = messages + [
                HumanMessage(content=title if turn == 0 else f"{title} {turn}"),
                AIMessage(content="reply"),
            ]
            add(
                turn * 2,
                {"messages": messages},
                tip_ts if turn == turns - 1 else "2024-01-01T00:00:01Z",
            )

    async def alist(self, config, *, filter=None, before=None, limit=None):
        self.alist_filters.append(filter)
        rows = sorted(self.rows, key=lambda r: r.config["configurable"]["checkpoint_id"])
        rows.reverse()
        yielded = 0
        for row in rows:
            if filter and any(row.metadata.get(key) != value for key, value in filter.items()):
                continue
            if (
                before
                and row.config["configurable"]["checkpoint_id"]
                >= (before["configurable"]["checkpoint_id"])
            ):
                continue
            yield row
            yielded += 1
            if limit is not None and yielded >= limit:
                return

    async def aget_tuple(self, config):
        thread_id = config["configurable"]["thread_id"]
        rows = [r for r in self.rows if r.config["configurable"]["thread_id"] == thread_id]
        if not rows:
            return None
        return max(rows, key=lambda r: r.config["configurable"]["checkpoint_id"])


async def chats(user_id: str = "user-123"):
    async with async_session_scope() as session:
        return list(await list_chats(session, user_id, limit=100))


@pytest.mark.asyncio
async def test_imports_each_thread_once_with_title_and_times() -> None:
    checkpointer = FakeCheckpointer()
    checkpointer.add_thread("t-1", title="First question", turns=3)
    checkpointer.add_thread("t-2", title="Second", agent_id="chatbot")

    assert await backfill.backfill_chats(checkpointer) == 2

    rows = {c.thread_id: c for c in await chats()}
    assert rows["t-1"].title == "First question"
    assert rows["t-1"].agent_id == "research-assistant"
    assert rows["t-2"].agent_id == "chatbot"
    assert rows["t-1"].updated_at.isoformat() == "2024-07-31T20:14:19.804150+00:00"


@pytest.mark.asyncio
async def test_skips_threads_without_owner_metadata() -> None:
    checkpointer = FakeCheckpointer()
    checkpointer.add_thread("owned")
    checkpointer.add_thread("orphan")
    for row in checkpointer.rows:
        if row.config["configurable"]["thread_id"] == "orphan":
            row.metadata.pop("user_id")

    await backfill.backfill_chats(checkpointer)

    assert [c.thread_id for c in await chats()] == ["owned"]


@pytest.mark.asyncio
async def test_pages_past_many_subgraph_heads() -> None:
    checkpointer = FakeCheckpointer()
    checkpointer.add_thread("older")
    checkpointer.add_thread("busy", subgraph_heads=backfill.PAGE_SIZE + 5)

    assert await backfill.backfill_chats(checkpointer) == 2
    assert sorted(c.thread_id for c in await chats()) == ["busy", "older"]


@pytest.mark.asyncio
async def test_bounds_total_rows_scanned() -> None:
    checkpointer = FakeCheckpointer()
    for i in range(6):
        checkpointer.add_thread(f"t-{i}")

    with patch.object(backfill, "PAGE_SIZE", 2), patch.object(backfill, "MAX_ROWS", 4):
        await backfill.backfill_chats(checkpointer)

    assert len(await chats()) == 4


@pytest.mark.asyncio
async def test_tolerates_missing_timestamp() -> None:
    checkpointer = FakeCheckpointer()
    checkpointer.add_thread("t-1", tip_ts=None)

    await backfill.backfill_chats(checkpointer)

    [chat] = await chats()
    assert chat.updated_at is not None


@pytest.mark.asyncio
async def test_runs_once_and_keeps_existing_rows() -> None:
    checkpointer = FakeCheckpointer()
    checkpointer.add_thread("t-1", title="Original")
    assert await backfill.backfill_chats(checkpointer) == 1

    checkpointer.add_thread("t-2")
    assert await backfill.backfill_chats(checkpointer) == 0
    assert [c.title for c in await chats()] == ["Original"]


@pytest.mark.parametrize("limit", [0, -1, 101, 999999])
def test_threads_rejects_out_of_range_limit(test_client, limit: int) -> None:
    """/threads and /chats bound limit so a client can't ask for an unbounded list."""
    for path in ("/threads", "/chats"):
        response = test_client.get(path, params={"user_id": "user-123", "limit": limit})
        assert response.status_code == 422

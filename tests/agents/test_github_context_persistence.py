"""Run context must never be written to checkpoints, unlike `configurable` values."""

from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.runtime import Runtime

TOKEN = "ghu_never_persist_me"


@dataclass
class Ctx:
    github_token: str | None = None


@pytest.mark.asyncio
async def test_context_token_is_not_persisted():
    seen: list[str | None] = []

    def node(state: MessagesState, runtime: Runtime[Ctx]):
        seen.append(runtime.context.github_token)
        return {"messages": [("ai", "done")]}

    saver = InMemorySaver()
    graph = (
        StateGraph(MessagesState, context_schema=Ctx)
        .add_node("node", node)
        .add_edge(START, "node")
        .compile(checkpointer=saver)
    )
    config = {"configurable": {"thread_id": "t1", "user_id": "u1"}, "metadata": {"agent_id": "a"}}
    await graph.ainvoke({"messages": [("user", "hi")]}, config, context=Ctx(github_token=TOKEN))

    assert seen == [TOKEN]
    checkpoints = [c async for c in saver.alist(None)]
    assert checkpoints
    assert all(TOKEN not in repr(c) for c in checkpoints)
    assert all(c.metadata.get("user_id") == "u1" for c in checkpoints)

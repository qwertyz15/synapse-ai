"""The research assistant gains GitHub tools only for runs that carry a GitHub token."""

from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from agents import research_assistant as ra
from agents.github_tools import AgentContext

seen_tokens: list[str | None] = []


@tool
def list_commits(repo: str, runtime: ToolRuntime) -> str:
    """List commits in a repository."""
    seen_tokens.append(runtime.context.github_token)
    return f"3 commits in {repo}"


class ToolCallingFake(FakeMessagesListChatModel):
    bound: list[list[str]] = []

    def bind_tools(self, tools: Any, **kwargs: Any):  # type: ignore[override]
        self.bound.append([t.name for t in tools])
        return self


def _model(*responses: AIMessage) -> ToolCallingFake:
    return ToolCallingFake(responses=list(responses), bound=[])


async def _run(model: ToolCallingFake, context: AgentContext | None):
    with (
        patch.object(ra, "get_model", return_value=model),
        patch.object(ra.github_tools, "get", side_effect=lambda write: [list_commits]),
        patch.object(ra, "list_indexed_documents", return_value=[]),
    ):
        return await ra.research_assistant.ainvoke(
            {"messages": [("user", "hi")]}, {"configurable": {"thread_id": "t"}}, context=context
        )


@pytest.mark.asyncio
async def test_without_token_only_base_tools_are_offered():
    model = _model(AIMessage(content="hello"))
    await _run(model, AgentContext())
    assert "list_commits" not in model.bound[0]
    assert "DocumentSearch" in model.bound[0]


@pytest.mark.asyncio
async def test_with_token_github_tools_run_with_the_callers_token():
    seen_tokens.clear()
    call = {"name": "list_commits", "args": {"repo": "o/r"}, "id": "c1", "type": "tool_call"}
    model = _model(
        AIMessage(content="", tool_calls=[call]), AIMessage(content="There are 3 commits.")
    )
    result = await _run(model, AgentContext(github_token="ghu_user", github_login="octo"))

    assert "list_commits" in model.bound[0] and "DocumentSearch" in model.bound[0]
    assert seen_tokens == ["ghu_user"]
    tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_message.content == "3 commits in o/r"
    assert result["messages"][-1].content == "There are 3 commits."


def test_instructions_mention_github_only_when_connected():
    with patch.object(ra, "list_indexed_documents", return_value=[]):
        assert "connected GitHub" not in ra.build_instructions(AgentContext())
        read_only = ra.build_instructions(AgentContext(github_token="ghu_x", github_login="octo"))
        writable = ra.build_instructions(AgentContext(github_token="ghu_x", github_write=True))
    assert "connected GitHub as @octo" in read_only and "read-only" in read_only
    assert "Changes are allowed" in writable

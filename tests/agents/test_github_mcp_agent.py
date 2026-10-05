"""Tests for the dedicated GitHub MCP Agent."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from agents.github_mcp_agent.github_mcp_agent import GitHubMCPAgent, prompt
from agents.github_tools import AgentContext
from core.settings import settings

ENSURE = "agents.github_mcp_agent.github_mcp_agent.github_tools.ensure"


@pytest.fixture
def fake_model():
    with patch("agents.github_mcp_agent.github_mcp_agent.get_model", return_value=Mock()):
        yield


class TestGitHubMCPAgent:
    def test_initialization(self):
        agent = GitHubMCPAgent()
        assert not agent._loaded
        assert agent._mcp_tools == []

    @pytest.mark.asyncio
    async def test_load_without_pat_defers_tools(self, fake_model):
        agent = GitHubMCPAgent()
        with patch.object(settings, "GITHUB_PAT", None), patch(ENSURE, AsyncMock()) as ensure:
            await agent.load()
        ensure.assert_not_awaited()
        assert agent._loaded and agent._graph is not None

    @pytest.mark.asyncio
    async def test_load_with_pat_uses_write_mode_tools(self, fake_model):
        agent = GitHubMCPAgent()
        tools = [Mock(), Mock()]
        with (
            patch.object(settings, "GITHUB_PAT", Mock()),
            patch(ENSURE, AsyncMock(return_value=tools)) as ensure,
            patch("agents.github_mcp_agent.github_mcp_agent.create_agent", return_value=Mock()),
        ):
            await agent.load()
        ensure.assert_awaited_once_with(None, write=True)
        assert agent._mcp_tools == tools

    @pytest.mark.asyncio
    async def test_ensure_tools_rebuilds_once_and_keeps_memory(self, fake_model):
        agent = GitHubMCPAgent()
        with patch.object(settings, "GITHUB_PAT", None):
            await agent.load()
        saver, store = object(), object()
        agent._graph.checkpointer = saver
        agent._graph.store = store

        with (
            patch(ENSURE, AsyncMock(return_value=[Mock()])) as ensure,
            patch("agents.github_mcp_agent.github_mcp_agent.create_agent", return_value=Mock()),
        ):
            await agent.ensure_tools(None)
            await agent.ensure_tools("ghu_user")
            await agent.ensure_tools("ghu_other")

        ensure.assert_awaited_once_with("ghu_user", write=True)
        assert agent._graph.checkpointer is saver
        assert agent._graph.store is store

    def test_create_graph_uses_context_schema(self):
        agent = GitHubMCPAgent()
        with (
            patch("agents.github_mcp_agent.github_mcp_agent.get_model") as get_model,
            patch("agents.github_mcp_agent.github_mcp_agent.create_agent") as create_agent,
        ):
            agent._create_graph()
        create_agent.assert_called_once_with(
            model=get_model.return_value,
            tools=[],
            name="github-mcp-agent",
            system_prompt=prompt,
            context_schema=AgentContext,
        )

    def test_get_graph_not_loaded(self):
        with pytest.raises(RuntimeError, match="Agent not loaded. Call load\\(\\) first."):
            GitHubMCPAgent().get_graph()

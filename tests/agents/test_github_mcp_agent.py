"""Tests for the GitHub MCP Agent."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.types import CallToolResult, Tool

from agents.github_mcp_agent import github_mcp_agent as module
from agents.github_mcp_agent.github_mcp_agent import GitHubContext, GitHubMCPAgent, prompt
from core.settings import settings

PAT = Mock(get_secret_value=Mock(return_value="ghp_servicetoken"))
MCP_TOOLS = [
    Tool(
        name="list_commits",
        description="List commits",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(name="get_me", description="Who am I", inputSchema={"type": "object", "properties": {}}),
]


@pytest.fixture
def fake_model():
    with patch("agents.github_mcp_agent.github_mcp_agent.get_model", return_value=Mock()):
        yield


@pytest.fixture
def no_pat():
    with patch.object(settings, "GITHUB_PAT", None):
        yield


class TestLoading:
    def test_initialization(self):
        agent = GitHubMCPAgent()
        assert not agent._loaded
        assert agent._mcp_tools == []

    @pytest.mark.asyncio
    async def test_load_without_pat_defers_tools(self, fake_model, no_pat):
        agent = GitHubMCPAgent()
        with patch.object(module, "_list_tools", AsyncMock()) as list_tools:
            await agent.load()
        list_tools.assert_not_awaited()
        assert agent._loaded
        assert agent._mcp_tools == []
        assert agent._graph is not None

    @pytest.mark.asyncio
    async def test_load_with_pat_lists_tools(self, fake_model):
        agent = GitHubMCPAgent()
        with (
            patch.object(settings, "GITHUB_PAT", PAT),
            patch.object(module, "_list_tools", AsyncMock(return_value=MCP_TOOLS)) as list_tools,
        ):
            await agent.load()
        list_tools.assert_awaited_once_with("ghp_servicetoken")
        assert [t.name for t in agent._mcp_tools] == ["list_commits", "get_me"]

    @pytest.mark.asyncio
    async def test_load_error_is_logged_without_token(self, fake_model, caplog):
        agent = GitHubMCPAgent()
        error = Exception("401 for Authorization: Bearer ghp_servicetoken")
        with (
            patch.object(settings, "GITHUB_PAT", PAT),
            patch.object(module, "_list_tools", AsyncMock(side_effect=error)),
            caplog.at_level(logging.ERROR),
        ):
            await agent.load()
        assert agent._mcp_tools == []
        assert agent._graph is not None
        assert "ghp_servicetoken" not in caplog.text
        assert "ghp_***" in caplog.text

    @pytest.mark.asyncio
    async def test_ensure_tools_loads_once_and_keeps_memory(self, fake_model, no_pat):
        agent = GitHubMCPAgent()
        await agent.load()
        saver, store = object(), object()
        agent._graph.checkpointer = saver
        agent._graph.store = store

        with patch.object(module, "_list_tools", AsyncMock(return_value=MCP_TOOLS)) as list_tools:
            await agent.ensure_tools(None)
            list_tools.assert_not_awaited()
            await agent.ensure_tools("ghu_usertoken")
            await agent.ensure_tools("ghu_othertoken")

        list_tools.assert_awaited_once_with("ghu_usertoken")
        assert len(agent._mcp_tools) == 2
        assert agent._graph.checkpointer is saver
        assert agent._graph.store is store

    def test_create_graph_uses_context_schema(self):
        agent = GitHubMCPAgent()
        agent._mcp_tools = [Mock(), Mock()]
        with (
            patch("agents.github_mcp_agent.github_mcp_agent.get_model") as mock_get_model,
            patch("agents.github_mcp_agent.github_mcp_agent.create_agent") as mock_create_agent,
        ):
            graph = agent._create_graph()

        assert graph == mock_create_agent.return_value
        mock_create_agent.assert_called_once_with(
            model=mock_get_model.return_value,
            tools=agent._mcp_tools,
            name="github-mcp-agent",
            system_prompt=prompt,
            context_schema=GitHubContext,
        )

    def test_get_graph_not_loaded(self):
        with pytest.raises(RuntimeError, match="Agent not loaded. Call load\\(\\) first."):
            GitHubMCPAgent().get_graph()


class TestAuthorization:
    @staticmethod
    def _request(token: str | None):
        runtime = SimpleNamespace(context=GitHubContext(github_token=token))
        return module.MCPToolCallRequest(
            name="get_me", args={}, server_name="github", runtime=runtime
        )

    @pytest.mark.asyncio
    async def test_user_token_wins_over_pat(self):
        handler = AsyncMock(return_value="ok")
        with patch.object(settings, "GITHUB_PAT", PAT):
            assert await module._authorize(self._request("ghu_usertoken"), handler) == "ok"
        sent = handler.await_args.args[0]
        assert sent.headers == {"Authorization": "Bearer ghu_usertoken"}

    @pytest.mark.asyncio
    async def test_falls_back_to_pat(self):
        handler = AsyncMock(return_value="ok")
        with patch.object(settings, "GITHUB_PAT", PAT):
            await module._authorize(self._request(None), handler)
        assert handler.await_args.args[0].headers == {"Authorization": "Bearer ghp_servicetoken"}

    @pytest.mark.asyncio
    async def test_without_any_token_returns_error(self, no_pat):
        handler = AsyncMock()
        result = await module._authorize(self._request(None), handler)
        handler.assert_not_awaited()
        assert isinstance(result, CallToolResult)
        assert result.isError
        assert "Connect GitHub" in result.content[0].text

    def test_tool_connections_carry_no_credentials(self):
        assert module._connection()["headers"] == {}
        assert module._connection("ghu_x")["headers"] == {"Authorization": "Bearer ghu_x"}

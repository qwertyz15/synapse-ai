"""Tests for the shared GitHub MCP tools."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from mcp.types import CallToolResult, Tool

from agents import github_tools as module
from agents.github_tools import AgentContext, GitHubTools
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
def no_pat():
    with patch.object(settings, "GITHUB_PAT", None):
        yield


def _request(context: AgentContext | None):
    return module.MCPToolCallRequest(
        name="get_me", args={}, server_name="github", runtime=SimpleNamespace(context=context)
    )


class TestConnection:
    def test_limits_toolsets_and_defaults_to_read_only(self):
        headers = module.connection()["headers"]
        assert headers == {
            "X-MCP-Toolsets": "context,repos,issues,pull_requests",
            "X-MCP-Readonly": "true",
        }

    def test_write_mode_and_token(self):
        headers = module.connection("ghu_x", write=True)["headers"]
        assert headers["X-MCP-Readonly"] == "false"
        assert headers["Authorization"] == "Bearer ghu_x"

    def test_redact(self):
        assert (
            module.redact("Bearer ghu_abc123 and github_pat_11A_x")
            == "Bearer ghu_*** and github_pat_***"
        )


class TestAuthorize:
    @pytest.mark.asyncio
    async def test_user_token_and_read_only_by_default(self):
        handler = AsyncMock(return_value="ok")
        with patch.object(settings, "GITHUB_PAT", PAT):
            assert (
                await module._authorize(_request(AgentContext(github_token="ghu_user")), handler)
                == "ok"
            )
        headers = handler.await_args.args[0].headers
        assert headers["Authorization"] == "Bearer ghu_user"
        assert headers["X-MCP-Readonly"] == "true"

    @pytest.mark.asyncio
    async def test_write_flag_comes_from_the_run(self):
        handler = AsyncMock()
        await module._authorize(
            _request(AgentContext(github_token="ghu_user", github_write=True)), handler
        )
        assert handler.await_args.args[0].headers["X-MCP-Readonly"] == "false"

    @pytest.mark.asyncio
    async def test_falls_back_to_pat_without_a_context(self):
        handler = AsyncMock()
        with patch.object(settings, "GITHUB_PAT", PAT):
            await module._authorize(_request(None), handler)
        assert handler.await_args.args[0].headers["Authorization"] == "Bearer ghp_servicetoken"

    @pytest.mark.asyncio
    async def test_without_any_token_returns_error(self, no_pat):
        handler = AsyncMock()
        result = await module._authorize(_request(AgentContext()), handler)
        handler.assert_not_awaited()
        assert isinstance(result, CallToolResult) and result.isError
        assert "Connect GitHub" in result.content[0].text


class TestCache:
    @pytest.mark.asyncio
    async def test_lists_once_per_mode(self, no_pat):
        cache = GitHubTools()
        with patch.object(module, "_list_tools", AsyncMock(return_value=MCP_TOOLS)) as list_tools:
            assert await cache.ensure(None) == []
            read = await cache.ensure("ghu_a")
            again = await cache.ensure("ghu_b")
            write = await cache.ensure("ghu_a", write=True)

        assert [c.args for c in list_tools.await_args_list] == [("ghu_a", False), ("ghu_a", True)]
        assert read is again
        assert [t.name for t in read] == [t.name for t in write] == ["list_commits", "get_me"]
        assert cache.get(False) is read and cache.get(True) is write

    @pytest.mark.asyncio
    async def test_cached_tools_hold_no_credentials(self, no_pat):
        cache = GitHubTools()
        with (
            patch.object(module, "_list_tools", AsyncMock(return_value=MCP_TOOLS)),
            patch.object(module, "convert_mcp_tool_to_langchain_tool") as convert,
        ):
            await cache.ensure("ghu_secret")
        for call in convert.call_args_list:
            assert "Authorization" not in call.kwargs["connection"]["headers"]

    @pytest.mark.asyncio
    async def test_load_error_is_logged_without_token(self, caplog, no_pat):
        cache = GitHubTools()
        error = Exception("401 for Authorization: Bearer ghu_secret123")
        with (
            patch.object(module, "_list_tools", AsyncMock(side_effect=error)),
            caplog.at_level(logging.ERROR),
        ):
            assert await cache.ensure("ghu_secret123") == []
        assert "ghu_secret123" not in caplog.text
        assert "ghu_***" in caplog.text

"""GitHub MCP tools shared by agents, called with each user's own token.

Tool definitions are listed once per mode (read-only / write) and hold no credentials. On every call
the `_authorize` interceptor adds the run's token and read-only flag from `AgentContext`, so a token
is only ever held in memory for the duration of a run.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.sessions import StreamableHttpConnection, create_session
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from mcp.types import CallToolResult, PaginatedRequestParams, TextContent, Tool

from core import settings

logger = logging.getLogger(__name__)

TOOLSETS = "context,repos,issues,pull_requests"
NOT_CONNECTED = 'GitHub isn\'t connected. Click "Connect GitHub" in the sidebar and try again.'


@dataclass
class AgentContext:
    """Per-run context. Kept out of `configurable` because LangGraph persists those values."""

    github_token: str | None = None
    github_login: str | None = None
    github_write: bool = False


def redact(text: str) -> str:
    return re.sub(r"(gh[a-z]_|github_pat_)[A-Za-z0-9_]+", r"\1***", text)


def _pat() -> str | None:
    return settings.GITHUB_PAT.get_secret_value() if settings.GITHUB_PAT else None


def _mode_headers(write: bool) -> dict[str, str]:
    return {"X-MCP-Toolsets": TOOLSETS, "X-MCP-Readonly": "false" if write else "true"}


def connection(token: str | None = None, write: bool = False) -> StreamableHttpConnection:
    headers = _mode_headers(write)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return StreamableHttpConnection(
        transport="streamable_http", url=settings.MCP_GITHUB_SERVER_URL, headers=headers
    )


async def _authorize(request: MCPToolCallRequest, handler):
    context = getattr(request.runtime, "context", None)
    token = getattr(context, "github_token", None) or _pat()
    if not token:
        return CallToolResult(content=[TextContent(type="text", text=NOT_CONNECTED)], isError=True)
    write = bool(getattr(context, "github_write", False))
    headers = {**_mode_headers(write), "Authorization": f"Bearer {token}"}
    return await handler(request.override(headers=headers))


async def _list_tools(token: str, write: bool) -> list[Tool]:
    tools: list[Tool] = []
    async with create_session(connection(token, write)) as session:
        await session.initialize()
        cursor: str | None = None
        while True:
            params = PaginatedRequestParams(cursor=cursor) if cursor else None
            page = await session.list_tools(params=params)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                return tools


class GitHubTools:
    """Caches GitHub's tool list per mode; listing needs any valid token, calls use the caller's."""

    def __init__(self) -> None:
        self._tools: dict[bool, list[BaseTool]] = {}
        self._lock = asyncio.Lock()

    def get(self, write: bool = False) -> list[BaseTool]:
        return self._tools.get(write, [])

    async def ensure(self, token: str | None, write: bool = False) -> list[BaseTool]:
        token = token or _pat()
        if write in self._tools or not token:
            return self.get(write)
        async with self._lock:
            if write not in self._tools:
                await self._load(token, write)
        return self.get(write)

    async def _load(self, token: str, write: bool) -> None:
        try:
            tools = await _list_tools(token, write)
        except Exception as e:
            logger.error(f"Failed to load GitHub MCP tools: {redact(str(e))}")
            return
        self._tools[write] = [
            convert_mcp_tool_to_langchain_tool(
                None,
                tool,
                connection=connection(write=write),
                tool_interceptors=[_authorize],
                server_name="github",
            )
            for tool in tools
        ]
        mode = "write" if write else "read-only"
        logger.info(f"Loaded {len(self._tools[write])} GitHub MCP tools ({mode})")


github_tools = GitHubTools()

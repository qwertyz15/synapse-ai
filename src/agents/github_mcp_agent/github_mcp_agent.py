"""GitHub MCP Agent - An agent that uses GitHub MCP tools for repository management."""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from langchain_mcp_adapters.sessions import StreamableHttpConnection, create_session
from langchain_mcp_adapters.tools import convert_mcp_tool_to_langchain_tool
from langgraph.graph.state import CompiledStateGraph
from mcp.types import CallToolResult, PaginatedRequestParams, TextContent, Tool

from agents.lazy_agent import LazyLoadingAgent
from core import get_model, settings

logger = logging.getLogger(__name__)

current_date = datetime.now().strftime("%B %d, %Y")
prompt = f"""
You are GitHubBot, a specialized assistant for GitHub repository management and development workflows.
You have access to GitHub MCP tools that allow you to interact with GitHub repositories, issues, pull requests,
and other GitHub resources. Today's date is {current_date}.

Your capabilities include:
- Repository management (create, clone, browse)
- Issue management (create, list, update, close)
- Pull request management (create, review, merge)
- Branch management (create, switch, merge)
- File operations (read, write, search)
- Commit operations (create, view history)

Guidelines:
- Always be helpful and provide clear explanations of GitHub operations
- When creating or modifying content, ensure it follows best practices
- Be cautious with destructive operations (deletes, force pushes, etc.)
- Provide context about what you're doing and why
- Use appropriate commit messages and PR descriptions
- Respect repository permissions and access controls

NOTE: You have access to GitHub MCP tools that provide direct GitHub API access.
If you have no GitHub tools, tell the user to click "Connect GitHub" in the sidebar first.
"""

NOT_CONNECTED = 'GitHub isn\'t connected. Click "Connect GitHub" in the sidebar and try again.'


@dataclass
class GitHubContext:
    """Per-run context. Kept out of `configurable` because LangGraph persists those values."""

    github_token: str | None = None


def _redact(text: str) -> str:
    return re.sub(r"(gh[a-z]_|github_pat_)[A-Za-z0-9_]+", r"\1***", text)


def _token_for(runtime: object | None) -> str | None:
    context = getattr(runtime, "context", None)
    token = getattr(context, "github_token", None)
    if token:
        return token
    return settings.GITHUB_PAT.get_secret_value() if settings.GITHUB_PAT else None


async def _authorize(request: MCPToolCallRequest, handler):
    token = _token_for(request.runtime)
    if not token:
        return CallToolResult(content=[TextContent(type="text", text=NOT_CONNECTED)], isError=True)
    return await handler(request.override(headers={"Authorization": f"Bearer {token}"}))


def _connection(token: str | None = None) -> StreamableHttpConnection:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return StreamableHttpConnection(
        transport="streamable_http", url=settings.MCP_GITHUB_SERVER_URL, headers=headers
    )


async def _list_tools(token: str) -> list[Tool]:
    tools: list[Tool] = []
    async with create_session(_connection(token)) as session:
        await session.initialize()
        cursor: str | None = None
        while True:
            params = PaginatedRequestParams(cursor=cursor) if cursor else None
            page = await session.list_tools(params=params)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                return tools


class GitHubMCPAgent(LazyLoadingAgent):
    """GitHub MCP agent that calls GitHub's MCP server with each user's own token.

    Tool definitions are listed once and hold no credentials; the token for every call comes
    from the run's `GitHubContext` (falling back to GITHUB_PAT) via the `_authorize` interceptor.
    """

    def __init__(self) -> None:
        super().__init__()
        self._mcp_tools: list[BaseTool] = []
        self._tools_lock = asyncio.Lock()

    async def load(self) -> None:
        """Build the graph, listing tools up front only when a service-wide GITHUB_PAT is set."""
        if settings.GITHUB_PAT:
            await self._load_tools(settings.GITHUB_PAT.get_secret_value())
        else:
            logger.info("GITHUB_PAT is not set; GitHub tools load when a user connects GitHub")
        self._graph = self._create_graph()
        self._loaded = True

    async def ensure_tools(self, token: str | None) -> None:
        """Load the tool list with the caller's token if it hasn't been loaded yet."""
        if self._mcp_tools or not token:
            return
        async with self._tools_lock:
            if self._mcp_tools:
                return
            await self._load_tools(token)
            if self._mcp_tools and self._graph is not None:
                previous = self._graph
                self._graph = self._create_graph()
                self._graph.checkpointer = previous.checkpointer
                self._graph.store = previous.store

    async def _load_tools(self, token: str) -> None:
        try:
            tools = await _list_tools(token)
        except Exception as e:
            logger.error(f"Failed to load GitHub MCP tools: {_redact(str(e))}")
            return
        self._mcp_tools = [
            convert_mcp_tool_to_langchain_tool(
                None,
                tool,
                connection=_connection(),
                tool_interceptors=[_authorize],
                server_name="github",
            )
            for tool in tools
        ]
        logger.info(f"GitHub MCP agent initialized with {len(self._mcp_tools)} tools")

    def _create_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Create the GitHub MCP agent graph."""
        model = get_model(settings.DEFAULT_MODEL)

        return create_agent(
            model=model,
            tools=self._mcp_tools,
            name="github-mcp-agent",
            system_prompt=prompt,
            context_schema=GitHubContext,
        )


# Create the agent instance
github_mcp_agent = GitHubMCPAgent()

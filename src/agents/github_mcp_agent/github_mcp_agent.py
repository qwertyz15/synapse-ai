"""GitHub MCP Agent - An agent that uses GitHub MCP tools for repository management."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

from agents.github_tools import AgentContext, github_tools
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
Changes are only possible when the user has allowed them; if a write is rejected as read-only,
tell the user to turn on "Allow changes" in the GitHub menu.
"""


class GitHubMCPAgent(LazyLoadingAgent):
    """Dedicated GitHub agent. Binds the write-mode tool list; whether a call may write is decided
    per run by `AgentContext.github_write`, which the shared interceptor sends as X-MCP-Readonly."""

    def __init__(self) -> None:
        super().__init__()
        self._mcp_tools: list[BaseTool] = []
        self._rebuild_lock = asyncio.Lock()

    async def load(self) -> None:
        if settings.GITHUB_PAT:
            self._mcp_tools = await github_tools.ensure(None, write=True)
        else:
            logger.info("GITHUB_PAT is not set; GitHub tools load when a user connects GitHub")
        self._graph = self._create_graph()
        self._loaded = True

    async def ensure_tools(self, token: str | None) -> None:
        if self._mcp_tools or not token:
            return
        async with self._rebuild_lock:
            if self._mcp_tools:
                return
            tools = await github_tools.ensure(token, write=True)
            if tools and self._graph is not None:
                self._mcp_tools = tools
                previous = self._graph
                self._graph = self._create_graph()
                self._graph.checkpointer = previous.checkpointer
                self._graph.store = previous.store

    def _create_graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Create the GitHub MCP agent graph."""
        model = get_model(settings.DEFAULT_MODEL)

        return create_agent(
            model=model,
            tools=self._mcp_tools,
            name="github-mcp-agent",
            system_prompt=prompt,
            context_schema=AgentContext,
        )


# Create the agent instance
github_mcp_agent = GitHubMCPAgent()

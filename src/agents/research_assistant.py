import logging
import os
from datetime import datetime
from typing import Any, Literal

from langchain_community.tools import DuckDuckGoSearchResults, OpenWeatherMapQueryRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, OpenWeatherMapAPIWrapper
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langchain_core.tools import BaseTool
from langgraph.config import get_config
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from agents.github_tools import AgentContext, github_tools
from agents.safeguard import Safeguard, SafeguardOutput, SafetyAssessment
from agents.tools import calculator, database_search
from agents.utils import handle_tool_error
from core import get_model, settings
from ingestion.attachments import list_attachments, open_attachment_store
from ingestion.manifest import list_indexed_documents

logger = logging.getLogger(__name__)


class AgentState(MessagesState, total=False):
    """`total=False` is PEP589 specs.

    documentation: https://typing.readthedocs.io/en/latest/spec/typeddict.html#totality
    """

    safety: SafeguardOutput
    remaining_steps: RemainingSteps


# The wrapper's default region "wt-wt" makes ddgs query the nonexistent wt.wikipedia.org.
web_search = DuckDuckGoSearchResults(
    name="WebSearch", api_wrapper=DuckDuckGoSearchAPIWrapper(region="us-en")
)
tools = [web_search, calculator, database_search]

# Add weather tool if API key is set
# Register for an API key at https://openweathermap.org/api/
if settings.OPENWEATHERMAP_API_KEY:
    wrapper = OpenWeatherMapAPIWrapper(
        openweathermap_api_key=settings.OPENWEATHERMAP_API_KEY.get_secret_value()
    )
    tools.append(OpenWeatherMapQueryRun(name="Weather", api_wrapper=wrapper))

MAX_LISTED_DOCUMENTS = 50


def describe_documents() -> str:
    try:
        doc_ids = [row[0] for row in list_indexed_documents(settings.CHROMA_DB_PATH)]
    except Exception:
        logger.exception("Could not read the document index")
        return "The list of uploaded documents is unavailable right now."
    if not doc_ids:
        return "The user hasn't uploaded any documents, so DocumentSearch will find nothing."
    listed = ", ".join(doc_ids[:MAX_LISTED_DOCUMENTS])
    more = len(doc_ids) - MAX_LISTED_DOCUMENTS
    if more > 0:
        listed += f", and {more} more"
    return f"The user has uploaded these documents, searchable with DocumentSearch: {listed}."


def describe_attachments(thread_id: str | None, user_id: str | None) -> str:
    if not thread_id or not user_id or not os.path.isdir(settings.CHROMA_DB_PATH):
        return ""
    try:
        store = open_attachment_store(settings.CHROMA_DB_PATH)
        names = [row[0] for row in list_attachments(store, thread_id, user_id)]
    except Exception:
        logger.exception("Could not read this chat's attachments")
        return ""
    if not names:
        return ""
    return (
        f"The user attached these files to this chat, also searchable with DocumentSearch: "
        f"{', '.join(names)}. Follow-up questions in this chat are usually about them, so "
        "search them again for any detail you haven't already quoted; DocumentSearch returns "
        "passages from attached files first, marked (attached to this chat)."
    )


def describe_github(context: AgentContext | None) -> str:
    if not context or not context.github_token:
        return ""
    who = f" as @{context.github_login}" if context.github_login else ""
    access = (
        "Changes are allowed: you may create or update issues, pull requests and files, but state "
        "exactly what you will change and only do it when the user clearly asked for it."
        if context.github_write
        else "Access is read-only. If asked to change something on GitHub, explain that the user "
        'can turn on "Allow changes" in the GitHub menu.'
    )
    return f"""
    The user has connected GitHub{who}. Use the GitHub tools for questions about their repositories,
    files, commits, branches, issues and pull requests; use DocumentSearch and WebSearch alongside them
    when a question also needs those. Refer to repositories as owner/name. {access}
    """


def build_instructions(
    context: AgentContext | None = None, thread_id: str | None = None, user_id: str | None = None
) -> str:
    # Built per call so the date and document list stay current in a long-running service.
    current_date = datetime.now().strftime("%B %d, %Y")
    return f"""
    You are a helpful research assistant with the ability to search the web, search the user's
    uploaded documents, and use other tools.
    Today's date is {current_date}.

    {describe_documents()}
    {describe_attachments(thread_id, user_id)}
    {describe_github(context)}
    NOTE: THE USER CAN'T SEE THE TOOL RESPONSE.

    A few things to remember:
    - Choose tools by where the answer lives. Use DocumentSearch first for anything the uploaded
      documents might cover: questions about the user's organization, policies, projects, or
      anything named in those documents. Use WebSearch for public or current information. Use
      both when a question needs both. Answer directly without tools for general knowledge.
    - When an answer comes from the documents, cite the file and page shown in the search result,
      e.g. (Employee Handbook, page 4). If the documents don't contain the answer, say so before
      falling back to other sources.
    - For web results, include markdown-formatted links to any citations used in your response.
      Only include one or two citations per response unless more are needed. ONLY USE LINKS
      RETURNED BY THE TOOLS.
    - Use calculator tool with numexpr to answer math questions. The user does not understand numexpr,
      so for the final response, use human readable format - e.g. "300 * 200", not "(300 \\times 200)".
    - If a tool fails, try another tool that can answer the same question (e.g. WebSearch for the
      weather). If nothing works, tell the user plainly what you couldn't find and why.
    """


def run_tools(context: AgentContext | None) -> list[BaseTool]:
    if not context or not context.github_token:
        return list(tools)
    return [*tools, *github_tools.get(context.github_write)]


def wrap_model(
    model: BaseChatModel,
    context: AgentContext | None = None,
    configurable: dict[str, Any] | None = None,
) -> RunnableSerializable[AgentState, AIMessage]:
    bound_model = model.bind_tools(run_tools(context))
    configurable = configurable or {}
    instructions = build_instructions(
        context, configurable.get("thread_id"), configurable.get("user_id")
    )
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | bound_model  # type: ignore[return-value]


def format_safety_message(safety: SafeguardOutput) -> AIMessage:
    content = (
        f"This conversation was flagged for unsafe content: {', '.join(safety.unsafe_categories)}"
    )
    return AIMessage(content=content)


async def acall_model(state: AgentState, runtime: Runtime[AgentContext]) -> AgentState:
    config = get_config()
    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    model_runnable = wrap_model(m, runtime.context, config["configurable"])
    response = await model_runnable.ainvoke(state, config)

    if state["remaining_steps"] < 2 and response.tool_calls:
        return {
            "messages": [
                AIMessage(
                    id=response.id,
                    content="Sorry, need more steps to process this request.",
                )
            ]
        }
    # We return a list, because this will get added to the existing list
    return {"messages": [response]}


async def safeguard_input(state: AgentState, config: RunnableConfig) -> AgentState:
    safeguard = Safeguard()
    safety_output = await safeguard.ainvoke(state["messages"])
    return {"safety": safety_output, "messages": []}


async def block_unsafe_content(state: AgentState, config: RunnableConfig) -> AgentState:
    safety: SafeguardOutput = state["safety"]
    return {"messages": [format_safety_message(safety)]}


async def acall_tools(state: AgentState, runtime: Runtime[AgentContext]) -> AgentState:
    # Built per run because the connected GitHub tools differ between users and runs.
    node = ToolNode(run_tools(runtime.context), handle_tool_errors=handle_tool_error)
    return await node.ainvoke(state, get_config())


# Define the graph
agent = StateGraph(AgentState, context_schema=AgentContext)
agent.add_node("model", acall_model)
agent.add_node("tools", acall_tools)
agent.add_node("guard_input", safeguard_input)
agent.add_node("block_unsafe_content", block_unsafe_content)
agent.set_entry_point("guard_input")


# Check for unsafe input and block further processing if found
def check_safety(state: AgentState) -> Literal["unsafe", "safe"]:
    safety: SafeguardOutput = state["safety"]
    match safety.safety_assessment:
        case SafetyAssessment.UNSAFE:
            return "unsafe"
        case _:
            return "safe"


agent.add_conditional_edges(
    "guard_input", check_safety, {"unsafe": "block_unsafe_content", "safe": "model"}
)

# Always END after blocking unsafe content
agent.add_edge("block_unsafe_content", END)

# Always run "model" after "tools"
agent.add_edge("tools", "model")


# After "model", if there are tool calls, run "tools". Otherwise END.
def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise TypeError(f"Expected AIMessage, got {type(last_message)}")
    if last_message.tool_calls:
        return "tools"
    return "done"


agent.add_conditional_edges("model", pending_tool_calls, {"tools": "tools", "done": END})


research_assistant: CompiledStateGraph[Any, Any, Any, Any] = agent.compile()

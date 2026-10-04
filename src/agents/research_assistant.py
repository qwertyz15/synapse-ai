import logging
from datetime import datetime
from typing import Literal

from langchain_community.tools import DuckDuckGoSearchResults, OpenWeatherMapQueryRun
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper, OpenWeatherMapAPIWrapper
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode

from agents.safeguard import Safeguard, SafeguardOutput, SafetyAssessment
from agents.tools import calculator, database_search
from agents.utils import handle_tool_error
from core import get_model, settings
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


def build_instructions() -> str:
    # Built per call so the date and document list stay current in a long-running service.
    current_date = datetime.now().strftime("%B %d, %Y")
    return f"""
    You are a helpful research assistant with the ability to search the web, search the user's
    uploaded documents, and use other tools.
    Today's date is {current_date}.

    {describe_documents()}

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


def wrap_model(model: BaseChatModel) -> RunnableSerializable[AgentState, AIMessage]:
    bound_model = model.bind_tools(tools)
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=build_instructions())] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | bound_model  # type: ignore[return-value]


def format_safety_message(safety: SafeguardOutput) -> AIMessage:
    content = (
        f"This conversation was flagged for unsafe content: {', '.join(safety.unsafe_categories)}"
    )
    return AIMessage(content=content)


async def acall_model(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    model_runnable = wrap_model(m)
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


# Define the graph
agent = StateGraph(AgentState)
agent.add_node("model", acall_model)
agent.add_node("tools", ToolNode(tools, handle_tool_errors=handle_tool_error))
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


research_assistant = agent.compile()

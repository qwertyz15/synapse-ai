import inspect
import json
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse  # type: ignore[import-untyped]
from langfuse.langchain import (
    CallbackHandler,  # type: ignore[import-untyped]
)
from langgraph.types import Command, Interrupt
from langsmith import Client as LangsmithClient
from langsmith import uuid7

from agents import DEFAULT_AGENT, AgentGraph, get_agent, get_all_agent_info, load_agent
from agents.github_mcp_agent.github_mcp_agent import github_mcp_agent
from agents.github_tools import AgentContext, github_tools
from core import settings
from db.backfill import run_backfills
from db.chats import ChatAccessError, claim_chat, delete_chat, get_chat, list_chats, rename_chat
from db.engine import async_session_scope
from memory import initialize_database, initialize_store
from schema import (
    ChatHistory,
    ChatHistoryInput,
    ChatMessage,
    Feedback,
    FeedbackResponse,
    ServiceMetadata,
    StreamInput,
    ThreadDeleted,
    ThreadRename,
    ThreadSummary,
    UserInput,
    UserThreads,
    UserThreadsInput,
)
from service.agui import router as agui_router
from service.rag import remove_thread_attachments
from service.rag import router as rag_router
from service.threads import thread_owner
from service.utils import (
    convert_message_content_to_string,
    ensure_model_available,
    langchain_to_chat_message,
    messages_from_checkpoint,
    remove_tool_calls,
)

warnings.filterwarnings("ignore", category=LangChainBetaWarning)
logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


def verify_bearer(
    http_auth: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(description="Please provide AUTH_SECRET api key.", auto_error=False)),
    ],
) -> None:
    if not settings.AUTH_SECRET:
        return
    auth_secret = settings.AUTH_SECRET.get_secret_value()
    if not http_auth or http_auth.credentials != auth_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Configurable lifespan that initializes the appropriate database checkpointer, store,
    and agents with async loading - for example for starting up MCP clients.
    """
    if not settings.AUTH_SECRET:
        if not settings.is_local_only():
            raise RuntimeError(
                f"AUTH_SECRET is required when the service listens on {settings.HOST}. "
                "Set AUTH_SECRET, or set HOST=127.0.0.1 to keep it local."
            )
        logger.warning(
            "AUTH_SECRET is not configured; the API is unauthenticated but only "
            f"listening on {settings.HOST}."
        )
    try:
        # Initialize both checkpointer (for short-term memory) and store (for long-term memory)
        async with initialize_database() as saver, initialize_store() as store:
            # Set up both components
            if hasattr(saver, "setup"):  # ignore: union-attr
                await saver.setup()
            # Only setup store for Postgres as InMemoryStore doesn't need setup
            if hasattr(store, "setup"):  # ignore: union-attr
                await store.setup()

            # Configure agents with both memory components and async loading
            agents = get_all_agent_info()
            for a in agents:
                try:
                    await load_agent(a.key)
                    logger.info(f"Agent loaded: {a.key}")
                except Exception as e:
                    logger.error(f"Failed to load agent {a.key}: {e}")
                    # Continue with other agents rather than failing startup

                agent = get_agent(a.key)
                # Set checkpointer for thread-scoped memory (conversation history)
                agent.checkpointer = saver
                # Set store for long-term memory (cross-conversation knowledge)
                agent.store = store
            await run_backfills(saver)
            yield
    except Exception as e:
        logger.error(f"Error during database/store/agents initialization: {e}")
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)
router = APIRouter(dependencies=[Depends(verify_bearer)])
# AG-UI protocol endpoints inherit the same bearer auth - see service/agui.py
router.include_router(agui_router)
router.include_router(rag_router)


@router.get("/info")
async def info() -> ServiceMetadata:
    models = list(settings.AVAILABLE_MODELS)
    models.sort()
    return ServiceMetadata(
        agents=get_all_agent_info(),
        models=models,
        default_agent=DEFAULT_AGENT,
        default_model=settings.DEFAULT_MODEL,
    )


GITHUB_AGENT_ID = "github-mcp-agent"
CONTEXT_AGENT_IDS = {GITHUB_AGENT_ID, "research-assistant"}
TRUE_VALUES = {"1", "true", "yes", "on"}


def github_access(
    x_github_token: Annotated[str | None, Header(alias="X-GitHub-Token")] = None,
    x_github_login: Annotated[str | None, Header(alias="X-GitHub-Login")] = None,
    x_github_write: Annotated[str | None, Header(alias="X-GitHub-Write")] = None,
) -> AgentContext:
    return AgentContext(
        github_token=x_github_token or None,
        github_login=x_github_login or None,
        github_write=(x_github_write or "").strip().lower() in TRUE_VALUES,
    )


GitHubAccess = Annotated[AgentContext, Depends(github_access)]


async def _run_context(agent_id: str, access: AgentContext | None) -> AgentContext | None:
    # The token travels as run context, never in config, so it isn't written to checkpoints.
    if agent_id not in CONTEXT_AGENT_IDS:
        return None
    access = access or AgentContext()
    if agent_id == GITHUB_AGENT_ID:
        await github_mcp_agent.ensure_tools(access.github_token)
    elif access.github_token:
        await github_tools.ensure(access.github_token, access.github_write)
    return access


async def _claim_thread(user_input: UserInput, agent_id: str) -> None:
    """Record the chat and fill in missing ids; someone else's thread is reported as not found."""
    user_input.thread_id = user_input.thread_id or str(uuid4())
    try:
        async with async_session_scope() as session:
            chat = await claim_chat(
                session, user_input.thread_id, user_input.user_id, agent_id, user_input.message
            )
        user_input.user_id = chat.user_id
    except ChatAccessError:
        raise HTTPException(status_code=404, detail="Thread not found")


async def _handle_input(
    user_input: UserInput, agent: AgentGraph, agent_id: str, context: Any = None
) -> tuple[dict[str, Any], UUID]:
    """
    Parse user input and handle any required interrupt resumption.
    Returns kwargs for agent invocation and the run_id.
    """
    run_id = uuid7()
    thread_id = user_input.thread_id or str(uuid4())
    user_id = user_input.user_id or str(uuid4())

    configurable = {"thread_id": thread_id, "user_id": user_id}
    if user_input.model is not None:
        ensure_model_available(user_input.model)
        configurable["model"] = user_input.model

    callbacks: list[Any] = []
    if settings.LANGFUSE_TRACING:
        # Initialize Langfuse CallbackHandler for Langchain (tracing)
        langfuse_handler = CallbackHandler()

        callbacks.append(langfuse_handler)

    if user_input.agent_config:
        # Check for reserved keys (including 'model' even if not in configurable)
        reserved_keys = {"thread_id", "user_id", "model", "github_token"}
        if overlap := reserved_keys & user_input.agent_config.keys():
            raise HTTPException(
                status_code=422,
                detail=f"agent_config contains reserved keys: {overlap}",
            )
        configurable.update(user_input.agent_config)

    config = RunnableConfig(
        configurable=configurable,
        metadata={"user_id": user_id, "agent_id": agent_id},
        run_id=run_id,
        callbacks=callbacks,
    )

    # Check for interrupts that need to be resumed
    state = await agent.aget_state(config=config)

    interrupted_tasks = [
        task for task in state.tasks if hasattr(task, "interrupts") and task.interrupts
    ]

    input: Command | dict[str, Any]
    if interrupted_tasks:
        # assume user input is response to resume agent execution from interrupt
        input = Command(resume=user_input.message)
    else:
        extra = {"attachments": user_input.attachments} if user_input.attachments else {}
        input = {"messages": [HumanMessage(content=user_input.message, additional_kwargs=extra)]}

    kwargs: dict[str, Any] = {
        "input": input,
        "config": config,
    }
    if context is not None:
        kwargs["context"] = context

    return kwargs, run_id


@router.post("/{agent_id}/invoke", operation_id="invoke_with_agent_id")
@router.post("/invoke")
async def invoke(
    user_input: UserInput, github: GitHubAccess, agent_id: str = DEFAULT_AGENT
) -> ChatMessage:
    """
    Invoke an agent with user input to retrieve a final response.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.
    """
    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    await _claim_thread(user_input, agent_id)
    context = await _run_context(agent_id, github)
    agent: AgentGraph = get_agent(agent_id)
    kwargs, run_id = await _handle_input(user_input, agent, agent_id, context)

    try:
        response_events: list[tuple[str, Any]] = await agent.ainvoke(**kwargs, stream_mode=["updates", "values"])  # type: ignore # fmt: skip
        response_type, response = response_events[-1]
        # A run that stops on an interrupt reports it on the final event of either stream
        # mode, so check for the interrupt before falling back to the last message.
        if "__interrupt__" in response:
            # Return the value of the first interrupt as an AIMessage
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        elif response_type == "values":
            # Normal response, the agent completed successfully
            output = langchain_to_chat_message(response["messages"][-1])
        else:
            raise ValueError(f"Unexpected response type: {response_type}")

        output.run_id = str(run_id)
        return output
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


async def message_generator(
    user_input: StreamInput, agent_id: str = DEFAULT_AGENT, github: AgentContext | None = None
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    context = await _run_context(agent_id, github)
    agent: AgentGraph = get_agent(agent_id)
    kwargs, run_id = await _handle_input(user_input, agent, agent_id, context)

    try:
        # Process streamed events from the graph and yield messages over the SSE stream.
        async for stream_event in agent.astream(  # type: ignore[no-matching-overload]
            **kwargs, stream_mode=["updates", "messages", "custom"], subgraphs=True
        ):
            if not isinstance(stream_event, tuple):
                continue
            # Handle different stream event structures based on subgraphs
            if len(stream_event) == 3:
                # With subgraphs=True: (node_path, stream_mode, event)
                _, stream_mode, event = stream_event
            else:
                # Without subgraphs: (stream_mode, event)
                stream_mode, event = stream_event
            new_messages: list[Any] = []
            if stream_mode == "updates":
                for node, updates in event.items():
                    # A simple approach to handle agent interrupts.
                    # In a more sophisticated implementation, we could add
                    # some structured ChatMessage type to return the interrupt value.
                    if node == "__interrupt__":
                        interrupt: Interrupt
                        for interrupt in updates:
                            new_messages.append(AIMessage(content=interrupt.value))
                        continue
                    updates = updates or {}
                    update_messages = updates.get("messages", [])
                    # special cases for using langgraph-supervisor library
                    if "supervisor" in node or "sub-agent" in node:
                        # the only tools that come from the actual agent are the handoff and handback tools
                        if isinstance(update_messages[-1], ToolMessage):
                            if "sub-agent" in node and len(update_messages) > 1:
                                # If this is a sub-agent, we want to keep the last 2 messages - the handback tool, and it's result
                                update_messages = update_messages[-2:]
                            else:
                                # If this is a supervisor, we want to keep the last message only - the handoff result. The tool comes from the 'agent' node.
                                update_messages = [update_messages[-1]]
                        else:
                            update_messages = []
                    new_messages.extend(update_messages)

            if stream_mode == "custom":
                new_messages = [event]

            # LangGraph streaming may emit tuples: (field_name, field_value)
            # e.g. ('content', <str>), ('tool_calls', [ToolCall,...]), ('additional_kwargs', {...}), etc.
            # We accumulate only supported fields into `parts` and skip unsupported metadata.
            # More info at: https://langchain-ai.github.io/langgraph/cloud/how-tos/stream_messages/
            processed_messages = []
            current_message: dict[str, Any] = {}
            for message in new_messages:
                if isinstance(message, tuple):
                    key, value = message
                    # Store parts in temporary dict
                    current_message[key] = value
                else:
                    # Add complete message if we have one in progress
                    if current_message:
                        processed_messages.append(_create_ai_message(current_message))
                        current_message = {}
                    processed_messages.append(message)

            # Add any remaining message parts
            if current_message:
                processed_messages.append(_create_ai_message(current_message))

            for message in processed_messages:
                try:
                    chat_message = langchain_to_chat_message(message)
                    chat_message.run_id = str(run_id)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                    continue
                # LangGraph re-sends the input message, which feels weird, so drop it
                if chat_message.type == "human" and chat_message.content == user_input.message:
                    continue
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

            if stream_mode == "messages":
                if not user_input.stream_tokens:
                    continue
                msg, metadata = event
                if "skip_stream" in metadata.get("tags", []):
                    continue
                # For some reason, astream("messages") causes non-LLM nodes to send extra messages.
                # Drop them.
                if not isinstance(msg, AIMessageChunk):
                    continue
                content = remove_tool_calls(msg.content)
                if content:
                    # Empty content in the context of OpenAI usually means
                    # that the model is asking for a tool to be invoked.
                    # So we only print non-empty content.
                    yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
    except Exception as e:
        logger.error(f"Error in message generator: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _create_ai_message(parts: dict) -> AIMessage:
    sig = inspect.signature(AIMessage)
    valid_keys = set(sig.parameters)
    filtered = {k: v for k, v in parts.items() if k in valid_keys}
    return AIMessage(**filtered)


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@router.post(
    "/{agent_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
    operation_id="stream_with_agent_id",
)
@router.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream(
    user_input: StreamInput, github: GitHubAccess, agent_id: str = DEFAULT_AGENT
) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    await _claim_thread(user_input, agent_id)
    return StreamingResponse(
        message_generator(user_input, agent_id, github),
        media_type="text/event-stream",
    )


@router.post("/feedback")
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run to LangSmith.

    This is a simple wrapper for the LangSmith create_feedback API, so the
    credentials can be stored and managed in the service rather than the client.
    See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
    """
    client = LangsmithClient()
    kwargs = feedback.kwargs or {}
    client.create_feedback(
        run_id=feedback.run_id,
        key=feedback.key,
        score=feedback.score,
        **kwargs,
    )
    return FeedbackResponse()


@router.post("/{agent_id}/history", operation_id="history_with_agent_id")
@router.post("/history")
async def history(input: ChatHistoryInput, agent_id: str = DEFAULT_AGENT) -> ChatHistory:
    """
    Get chat history for a thread and agent.

    If agent_id is not provided, the default agent will be used.
    """
    if input.user_id is not None:
        async with async_session_scope() as session:
            chat = await get_chat(session, input.thread_id)
        if chat is None:
            return ChatHistory(messages=[])
        if chat.user_id != input.user_id:
            raise HTTPException(status_code=404, detail="Thread not found")
    agent: AgentGraph = get_agent(agent_id)
    config = RunnableConfig(configurable={"thread_id": input.thread_id})
    try:
        messages: list[BaseMessage] = []
        # Functional-API agents keep the conversation in `__previous__`, which aget_state
        # doesn't return, so read the raw checkpoint first and only fall back for graphs.
        checkpointer = getattr(agent, "checkpointer", None)
        if checkpointer:
            tup = await checkpointer.aget_tuple(config)
            if tup and "__previous__" in (tup.checkpoint.get("channel_values") or {}):
                messages = messages_from_checkpoint(tup.checkpoint)
        if not messages:
            state_snapshot = await agent.aget_state(config=config)
            # A thread that never existed (or was deleted) has no state values.
            messages = state_snapshot.values.get("messages", [])
        chat_messages: list[ChatMessage] = [langchain_to_chat_message(m) for m in messages]
        return ChatHistory(messages=chat_messages)
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@router.get("/{agent_id}/threads", operation_id="threads_with_agent_id")
@router.get("/threads")
async def threads(
    input: UserThreadsInput = Depends(), agent_id: str = DEFAULT_AGENT
) -> UserThreads:
    """
    List a user's conversation threads for an agent, most recently updated first.

    `user_id` is asserted by the caller and not checked against the credentials on the
    request, so any holder of the bearer token can list any user's threads - the same
    trust model as /history. Put your own authorization in front of this before end
    users can reach it.
    """
    return await _list_threads(input, agent_id)


@router.get("/chats")
async def all_chats(input: UserThreadsInput = Depends()) -> UserThreads:
    """List a user's conversations across every agent, most recently updated first."""
    return await _list_threads(input, None)


async def _list_threads(input: UserThreadsInput, agent_id: str | None) -> UserThreads:
    async with async_session_scope() as session:
        chats = await list_chats(session, input.user_id, agent_id, input.limit)
    return UserThreads(
        threads=[
            ThreadSummary(
                thread_id=c.thread_id, agent_id=c.agent_id, updated_at=c.updated_at, title=c.title
            )
            for c in chats
        ]
    )


@router.patch("/{agent_id}/threads/{thread_id}", operation_id="rename_thread_with_agent_id")
async def rename_thread(
    thread_id: str, user_id: str, rename: ThreadRename, agent_id: str = DEFAULT_AGENT
) -> ThreadSummary:
    """Rename a conversation. Someone else's thread is reported as not found."""
    async with async_session_scope() as session:
        chat = await rename_chat(session, thread_id, user_id, agent_id, rename.title)
        if chat is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        return ThreadSummary(
            thread_id=chat.thread_id,
            agent_id=chat.agent_id,
            updated_at=chat.updated_at,
            title=chat.title,
        )


@router.delete("/{agent_id}/threads/{thread_id}", operation_id="delete_thread_with_agent_id")
async def delete_thread(
    thread_id: str, user_id: str, agent_id: str = DEFAULT_AGENT
) -> ThreadDeleted:
    """
    Delete a conversation and every file attached to it.

    The thread must belong to `user_id` and `agent_id`; otherwise this returns 404 without
    revealing whether it exists. Same trust model for `user_id` as /threads.
    """
    agent: AgentGraph = get_agent(agent_id)
    checkpointer = getattr(agent, "checkpointer", None)
    async with async_session_scope() as session:
        chat = await get_chat(session, thread_id)
    if chat is not None:
        owner: tuple[str | None, str | None] | None = (chat.user_id, chat.agent_id)
    else:
        # Threads from before the chats table that the startup import hasn't recorded.
        owner = await thread_owner(checkpointer, thread_id) if checkpointer else None
    if owner is not None and owner != (user_id, agent_id):
        raise HTTPException(status_code=404, detail="Thread not found")

    if owner is not None and checkpointer is not None:
        await checkpointer.adelete_thread(thread_id)
    removed = await remove_thread_attachments(thread_id, user_id)
    async with async_session_scope() as session:
        await delete_chat(session, thread_id)
    if owner is None and not removed:
        raise HTTPException(status_code=404, detail="Thread not found")
    return ThreadDeleted(thread_id=thread_id, attachments_removed=removed)


@app.get("/health")
async def health_check():
    """Health check endpoint."""

    health_status = {"status": "ok"}

    if settings.LANGFUSE_TRACING:
        try:
            langfuse = Langfuse()
            health_status["langfuse"] = "connected" if langfuse.auth_check() else "disconnected"
        except Exception as e:
            logger.error(f"Langfuse connection error: {e}")
            health_status["langfuse"] = "disconnected"

    return health_status


app.include_router(router)

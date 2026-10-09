import re
from collections.abc import Mapping
from typing import Any, cast

from fastapi import HTTPException
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages import (
    ChatMessage as LangchainChatMessage,
)

from core import settings
from core.llm import PROVIDER_NAMES, provider_of, user_key_for
from schema import ChatMessage


def ensure_model_available(model: Any) -> None:
    """Raise 400 if `model` isn't in AVAILABLE_MODELS and the user has no own key for it."""
    if model not in settings.AVAILABLE_MODELS and not user_key_for(model):
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not available. "
            f"Allowed: {[m.value for m in settings.AVAILABLE_MODELS]}",
        )


def convert_message_content_to_string(content: str | list[str | dict]) -> str:
    if isinstance(content, str):
        return content
    text: list[str] = []
    for content_item in content:
        if isinstance(content_item, str):
            text.append(content_item)
            continue
        if content_item["type"] == "text":
            text.append(content_item["text"])
    return "".join(text)


def langchain_to_chat_message(message: BaseMessage) -> ChatMessage:
    """Create a ChatMessage from a LangChain message."""
    match message:
        case HumanMessage():
            human_message = ChatMessage(
                type="human",
                content=convert_message_content_to_string(message.content),
                attachments=list(message.additional_kwargs.get("attachments") or []),
            )
            return human_message
        case AIMessage():
            ai_message = ChatMessage(
                type="ai",
                content=convert_message_content_to_string(message.content),
            )
            if message.tool_calls:
                ai_message.tool_calls = message.tool_calls
            if message.response_metadata:
                ai_message.response_metadata = message.response_metadata
            return ai_message
        case ToolMessage():
            tool_message = ChatMessage(
                type="tool",
                content=convert_message_content_to_string(message.content),
                tool_call_id=message.tool_call_id,
                status=message.status,
            )
            return tool_message
        case LangchainChatMessage():
            if message.role == "custom":
                custom_message = ChatMessage(
                    type="custom",
                    content="",
                    custom_data=cast(dict[str, Any], message.content[0]),
                )
                return custom_message
            else:
                raise ValueError(f"Unsupported chat message role: {message.role}")
        case _:
            raise ValueError(f"Unsupported message type: {message.__class__.__name__}")


def messages_from_checkpoint(checkpoint: Mapping[str, Any]) -> list[BaseMessage]:
    """Extract a thread's conversation from a raw checkpoint.

    Graph-state agents keep the conversation in the `messages` channel. Functional-API
    (`@entrypoint`) agents keep it in `__previous__` instead, which `aget_state` does not
    surface - it only returns the entrypoint's final value.
    """
    channel_values = checkpoint.get("channel_values") or {}
    messages = channel_values.get("messages")
    if not messages:
        previous = channel_values.get("__previous__")
        if isinstance(previous, Mapping):
            messages = previous.get("messages")
        elif isinstance(previous, list):
            messages = previous
    return [m for m in (messages or []) if isinstance(m, BaseMessage)]


def remove_tool_calls(content: str | list[str | dict]) -> str | list[str | dict]:
    """Remove tool calls from content."""
    if isinstance(content, str):
        return content
    # Currently only Anthropic models stream tool calls, using content item type tool_use.
    return [
        content_item
        for content_item in content
        if isinstance(content_item, str) or content_item["type"] != "tool_use"
    ]


# Libraries whose errors come from a model provider's API; anything else is a bug, not the provider.
_PROVIDER_MODULES = {"openai", "anthropic", "google", "groq", "langchain_google_genai", "httpx"}


# How providers word a bad key when they don't answer 401 (Google says 400).
_BAD_KEY_PHRASES = (
    "API key not valid",
    "API_KEY_INVALID",
    "invalid_api_key",
    "Incorrect API key",
    "invalid x-api-key",
)


def describe_model_error(error: BaseException, model: str | None) -> str | None:
    """A message a user can act on for an error from the model provider, or None for other errors."""
    if not (
        isinstance(error, TimeoutError) or type(error).__module__.split(".")[0] in _PROVIDER_MODULES
    ):
        return None
    text = str(error)
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        found = re.search(r"\b(401|403|404|429)\b", text)
        status = int(found.group(1)) if found else None
    provider = PROVIDER_NAMES.get(provider_of(model) or "") if model else None
    who = provider or "The model provider"
    own = bool(model and user_key_for(model))
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return f"{who} didn't respond in time. Try again, or pick another model."
    if status == 429 or "RESOURCE_EXHAUSTED" in text or "insufficient_quota" in text:
        if own:
            return (
                f"{who} refused the request: your key has reached its quota or rate limit for "
                f"{model}. Free-tier keys often don't include every model; pick another model, or "
                f"check your plan and billing with {who}."
            )
        return f"{who} is limiting requests for {model} right now. Try again soon, or pick another model."
    if status == 401 or any(phrase in text for phrase in _BAD_KEY_PHRASES):
        return (
            f"{who} rejected your API key. Update it in Settings."
            if own
            else f"{who} rejected the API key."
        )
    if status == 403 or "PERMISSION_DENIED" in text:
        return (
            f"Your {who} key isn't allowed to use {model}."
            if own
            else f"{who} doesn't allow {model} on this account."
        )
    if status == 404 or "NOT_FOUND" in text or "model_not_found" in text:
        return f"{model} isn't available with this {who} key."
    return None

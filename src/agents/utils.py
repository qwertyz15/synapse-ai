import re
from typing import Any

from langchain_core.messages import ChatMessage
from langgraph.types import StreamWriter
from pydantic import BaseModel, Field


class CustomData(BaseModel):
    "Custom data being sent by an agent"

    data: dict[str, Any] = Field(description="The custom data")

    def to_langchain(self) -> ChatMessage:
        return ChatMessage(content=[self.data], role="custom")

    def dispatch(self, writer: StreamWriter) -> None:
        writer(self.to_langchain())


# Errors from HTTP clients can echo the request URL, which may carry a key (e.g. OpenWeatherMap's appid).
_SECRET_PARAM = re.compile(r"(?i)\b(appid|api_?key|key|token)=[^&\s'\"]+")


def handle_tool_error(e: Exception) -> str:
    """ToolNode error handler that reports failures back to the model instead of aborting the run."""
    message = _SECRET_PARAM.sub(r"\1=<redacted>", str(e))
    return (
        f"Tool failed with {type(e).__name__}: {message}\n"
        "Do not call it again with the same input. Use a different tool or approach, "
        "or tell the user what could not be done."
    )

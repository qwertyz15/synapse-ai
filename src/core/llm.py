from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache, lru_cache
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_aws import ChatBedrock
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai import ChatVertexAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from core.settings import settings
from schema.models import (
    AllModelEnum,
    AnthropicModelName,
    AWSModelName,
    AzureOpenAIModelName,
    DeepseekModelName,
    FakeModelName,
    GoogleModelName,
    GroqModelName,
    OllamaModelName,
    OpenAICompatibleName,
    OpenAIModelName,
    OpenRouterModelName,
    VertexAIModelName,
)

_MODEL_TABLE = (
    {m: m.value for m in OpenAIModelName}
    | {m: m.value for m in OpenAICompatibleName}
    | {m: m.value for m in AzureOpenAIModelName}
    | {m: m.value for m in DeepseekModelName}
    | {m: m.value for m in AnthropicModelName}
    | {m: m.value for m in GoogleModelName}
    | {m: m.value for m in VertexAIModelName}
    | {m: m.value for m in GroqModelName}
    | {m: m.value for m in AWSModelName}
    | {m: m.value for m in OllamaModelName}
    | {m: m.value for m in OpenRouterModelName}
    | {m: m.value for m in FakeModelName}
)


class FakeToolModel(FakeListChatModel):
    def __init__(self, responses: list[str]):
        super().__init__(responses=responses)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self


type ModelT = (
    AzureChatOpenAI
    | ChatOpenAI
    | ChatAnthropic
    | ChatGoogleGenerativeAI
    | ChatVertexAI
    | ChatGroq
    | ChatBedrock
    | ChatOllama
    | FakeToolModel
)


# Providers a user can bring their own API key for, and the models each key unlocks.
USER_KEY_PROVIDERS = {
    "openai": OpenAIModelName,
    "anthropic": AnthropicModelName,
    "deepseek": DeepseekModelName,
    "google": GoogleModelName,
    "groq": GroqModelName,
    "openrouter": OpenRouterModelName,
}

PROVIDER_NAMES = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "google": "Google",
    "groq": "Groq",
    "openrouter": "OpenRouter",
}

USER_KEY_TIMEOUT_S = 60

# The current request's own keys by provider; set only around one user's run.
_user_keys: ContextVar[dict[str, str] | None] = ContextVar("user_api_keys", default=None)


def provider_of(model_name: str) -> str | None:
    return next((p for p, names in USER_KEY_PROVIDERS.items() if model_name in names), None)


def models_for(provider: str) -> list[str]:
    return [m.value for m in USER_KEY_PROVIDERS.get(provider, [])]


@contextmanager
def user_api_keys(keys: dict[str, str]) -> Iterator[None]:
    """Use these keys (provider -> key) for models created during the block."""
    token = _user_keys.set(keys or None)
    try:
        yield
    finally:
        _user_keys.reset(token)


def user_key_for(model_name: str) -> str | None:
    keys = _user_keys.get()
    provider = provider_of(model_name)
    return keys.get(provider) if keys and provider else None


def get_model(model_name: AllModelEnum | None, /) -> ModelT:
    """The chat model for `model_name`, on the current user's own key when they set one."""
    if model_name is None:
        raise ValueError("Unsupported model: None")
    key = user_key_for(model_name)
    return _model_with_key(model_name, key) if key else _server_model(model_name)


@cache
def _server_model(model_name: AllModelEnum) -> ModelT:
    return _build(model_name, None)


@lru_cache(maxsize=256)
def _model_with_key(model_name: AllModelEnum, api_key: str) -> ModelT:
    return _build(model_name, api_key)


def _build(model_name: AllModelEnum, api_key: str | None) -> ModelT:
    # NOTE: models with streaming=True will send tokens as they are generated
    # if the /stream endpoint is called with stream_tokens=True (the default)
    # On a user's own key, fail fast: a free-tier key asking for a model outside its plan gets the
    # same 429 on every try, and retrying only keeps the chat "thinking".
    limits: dict[str, Any] = {"max_retries": 1, "timeout": USER_KEY_TIMEOUT_S} if api_key else {}
    key: dict[str, Any] = {"api_key": api_key, **limits} if api_key else {}
    api_model_name = _MODEL_TABLE.get(model_name)
    if not api_model_name:
        raise ValueError(f"Unsupported model: {model_name}")

    if model_name in OpenAIModelName:
        return ChatOpenAI(model=api_model_name, streaming=True, **key)
    if model_name in OpenAICompatibleName:
        if not settings.COMPATIBLE_BASE_URL or not settings.COMPATIBLE_MODEL:
            raise ValueError("OpenAICompatible base url and endpoint must be configured")

        return ChatOpenAI(
            model=settings.COMPATIBLE_MODEL,
            temperature=0.5,
            streaming=True,
            openai_api_base=settings.COMPATIBLE_BASE_URL,
            openai_api_key=settings.COMPATIBLE_API_KEY,
        )
    if model_name in AzureOpenAIModelName:
        if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_ENDPOINT:
            raise ValueError("Azure OpenAI API key and endpoint must be configured")

        # GPT-5 generation is reasoning-based and rejects temperature (400); omit it.
        return AzureChatOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            deployment_name=api_model_name,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            streaming=True,
            timeout=60,
            max_retries=3,
        )
    if model_name in DeepseekModelName:
        return ChatOpenAI(
            model=api_model_name,
            temperature=0.5,
            streaming=True,
            openai_api_base="https://api.deepseek.com",
            openai_api_key=api_key or settings.DEEPSEEK_API_KEY,
            **limits,
        )
    if model_name in AnthropicModelName:
        if model_name == AnthropicModelName.SONNET_5:
            # Claude Sonnet 5 rejects non-default sampling parameters (temperature,
            # top_p, top_k) with a 400 error -- adaptive thinking is on by default
            # instead. See https://docs.anthropic.com/en/docs/about-claude/models
            return ChatAnthropic(model_name=api_model_name, streaming=True, **key)
        return ChatAnthropic(model_name=api_model_name, temperature=0.5, streaming=True, **key)
    if model_name in GoogleModelName:
        # The Gemini SDK retries 6 times with backoff by default, ignoring 429 retry hints.
        return ChatGoogleGenerativeAI(
            model=api_model_name,
            temperature=0.5,
            streaming=True,
            **(key or {"max_retries": 2, "timeout": USER_KEY_TIMEOUT_S}),
        )
    if model_name in VertexAIModelName:
        return ChatVertexAI(model=api_model_name, temperature=0.5, streaming=True)
    if model_name in GroqModelName:
        if model_name == GroqModelName.GPT_OSS_SAFEGUARD_20B:
            return ChatGroq(model=api_model_name, temperature=0.0, **key)  # type: ignore[call-arg]
        return ChatGroq(model=api_model_name, temperature=0.5, **key)  # type: ignore[call-arg]
    if model_name in AWSModelName:
        if model_name == AWSModelName.BEDROCK_SONNET:
            # Sonnet 5 rejects non-default sampling params (400); omit temperature.
            return ChatBedrock(model=api_model_name)
        return ChatBedrock(model=api_model_name, temperature=0.5)
    if model_name in OllamaModelName:
        if not settings.OLLAMA_MODEL:
            raise ValueError("Ollama model must be configured")
        if settings.OLLAMA_BASE_URL:
            chat_ollama = ChatOllama(
                model=settings.OLLAMA_MODEL, temperature=0.5, base_url=settings.OLLAMA_BASE_URL
            )
        else:
            chat_ollama = ChatOllama(model=settings.OLLAMA_MODEL, temperature=0.5)
        return chat_ollama
    if model_name in OpenRouterModelName:
        # Without an explicit key the openai SDK falls back to OPENAI_API_KEY,
        # which would send that key to openrouter.ai.
        if not api_key and not settings.OPENROUTER_API_KEY:
            raise ValueError("OpenRouter API key must be configured")

        return ChatOpenAI(
            model=api_model_name,
            temperature=0.5,
            streaming=True,
            base_url="https://openrouter.ai/api/v1/",
            api_key=api_key or settings.OPENROUTER_API_KEY,
            **limits,
        )
    if model_name in FakeModelName:
        return FakeToolModel(responses=["This is a test response from the fake model."])

    raise ValueError(f"Unsupported model: {model_name}")

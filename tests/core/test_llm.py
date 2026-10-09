import os
from functools import partial
from unittest.mock import patch

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from core import llm
from core.llm import get_model
from schema.models import (
    AnthropicModelName,
    AzureOpenAIModelName,
    DeepseekModelName,
    FakeModelName,
    GoogleModelName,
    GroqModelName,
    OllamaModelName,
    OpenAIModelName,
    OpenRouterModelName,
)


def test_get_model_openai():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test_key"}):
        model = get_model(OpenAIModelName.GPT_5_NANO)
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-5-nano"
        assert model.streaming is True


def test_get_model_anthropic():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        model = get_model(AnthropicModelName.HAIKU_45)
        assert isinstance(model, ChatAnthropic)
        assert model.model == "claude-haiku-4-5"
        assert model.temperature == 0.5
        assert model.streaming is True


def test_get_model_anthropic_sonnet_5_omits_temperature():
    # Claude Sonnet 5 rejects non-default sampling parameters with a 400 error,
    # so get_model must not pass temperature for this model.
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        model = get_model(AnthropicModelName.SONNET_5)
        assert isinstance(model, ChatAnthropic)
        assert model.model == "claude-sonnet-5"
        assert model.streaming is True


def test_get_model_groq():
    with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
        model = get_model(GroqModelName.GPT_OSS_20B)
        assert isinstance(model, ChatGroq)
        assert model.model_name == "openai/gpt-oss-20b"
        assert model.temperature == 0.5


def test_get_model_groq_guard():
    with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
        model = get_model(GroqModelName.GPT_OSS_SAFEGUARD_20B)
        assert isinstance(model, ChatGroq)
        assert model.model_name == "openai/gpt-oss-safeguard-20b"
        assert model.temperature < 0.01


def test_get_model_groq_gpt_oss():
    with patch.dict(os.environ, {"GROQ_API_KEY": "test_key"}):
        model = get_model(GroqModelName.GPT_OSS_120B)
        assert isinstance(model, ChatGroq)
        assert model.model_name == "openai/gpt-oss-120b"
        # Only the safeguard variant gets the temperature=0.0 override.
        assert model.temperature == 0.5


def test_get_model_ollama():
    with patch("core.settings.settings.OLLAMA_MODEL", "llama3.3"):
        model = get_model(OllamaModelName.OLLAMA_GENERIC)
        assert isinstance(model, ChatOllama)
        assert model.model == "llama3.3"
        assert model.temperature == 0.5


# get_model caches models, so these build them directly: clearing the shared cache would evict
# entries later tests (and app startup) rely on.
_get_model_uncached = partial(llm._build, api_key=None)


def test_get_model_openrouter():
    with patch("core.settings.settings.OPENROUTER_API_KEY", SecretStr("test_key")):
        model = _get_model_uncached(OpenRouterModelName.GEMINI_36_FLASH)
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "google/gemini-3.6-flash"
        assert model.openai_api_base == "https://openrouter.ai/api/v1/"
        assert model.openai_api_key is not None
        assert model.openai_api_key.get_secret_value() == "test_key"
        assert model.temperature == 0.5
        assert model.streaming is True


def test_get_model_openrouter_requires_key():
    # An unset key must fail loudly: the openai SDK would otherwise fall back to
    # OPENAI_API_KEY and send it to openrouter.ai.
    with patch("core.settings.settings.OPENROUTER_API_KEY", None):
        with pytest.raises(ValueError, match="OpenRouter API key must be configured"):
            _get_model_uncached(OpenRouterModelName.GEMINI_36_FLASH)


def test_get_model_fake():
    model = get_model(FakeModelName.FAKE)
    assert isinstance(model, FakeListChatModel)
    assert model.responses == ["This is a test response from the fake model."]


def test_get_model_invalid():
    with pytest.raises(ValueError, match="Unsupported model:"):
        # Using type: ignore since we're intentionally testing invalid input
        get_model("invalid_model")  # type: ignore


def test_user_keys_apply_only_inside_the_block_and_only_to_their_provider():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-server"}):
        server = get_model(OpenAIModelName.GPT_5_NANO)
        with llm.user_api_keys({"openai": "sk-user", "deepseek": "ds-user"}):
            mine = get_model(OpenAIModelName.GPT_5_NANO)
            assert mine is not server
            assert mine.openai_api_key.get_secret_value() == "sk-user"
            assert get_model(OpenAIModelName.GPT_5_NANO) is mine
            deepseek = get_model(DeepseekModelName.DEEPSEEK_V4_FLASH)
            assert deepseek.openai_api_key.get_secret_value() == "ds-user"
        assert get_model(OpenAIModelName.GPT_5_NANO) is server


def test_provider_mapping():
    assert llm.provider_of(DeepseekModelName.DEEPSEEK_V4_FLASH) == "deepseek"
    assert llm.provider_of(AnthropicModelName.HAIKU_45) == "anthropic"
    assert llm.provider_of(AzureOpenAIModelName.AZURE_GPT_5_MINI) is None
    assert "claude-haiku-4-5" in llm.models_for("anthropic")
    assert llm.models_for("nope") == []


def test_models_on_a_users_key_fail_fast_and_gemini_retries_less():
    gemini = next(iter(GoogleModelName))
    with llm.user_api_keys({"google": "AIza-user-key", "openai": "sk-user"}):
        mine = get_model(gemini)
        assert (mine.max_retries, mine.timeout) == (1, llm.USER_KEY_TIMEOUT_S)
        assert get_model(OpenAIModelName.GPT_5_NANO).max_retries == 1
    with patch.dict(os.environ, {"GOOGLE_API_KEY": "AIza-server"}):
        server = _get_model_uncached(gemini)
        assert (server.max_retries, server.timeout) == (2, llm.USER_KEY_TIMEOUT_S)

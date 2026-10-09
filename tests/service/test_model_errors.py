"""Provider errors become messages the user can act on; other errors stay internal."""

from unittest.mock import patch

from core.llm import user_api_keys
from core.settings import settings
from schema.models import DeepseekModelName, GoogleModelName
from service.utils import describe_model_error

GEMINI = next(iter(GoogleModelName))


def provider_error(module: str, message: str, status: int | None = None) -> Exception:
    cls = type("APIError", (Exception,), {"__module__": module})
    error = cls(message)
    if status is not None:
        error.status_code = status
    return error


QUOTA = provider_error(
    "langchain_google_genai.chat_models", "429 RESOURCE_EXHAUSTED quota limit: 0"
)


def test_quota_on_the_users_own_key_points_at_their_plan():
    with user_api_keys({"google": "AIza-user"}):
        message = describe_model_error(QUOTA, GEMINI)
    assert "your key" in message and GEMINI in message and "Free-tier" in message


def test_quota_on_the_server_key_says_try_again():
    assert "Try again soon" in describe_model_error(QUOTA, GEMINI)


def test_rejected_keys_missing_models_and_timeouts():
    with user_api_keys({"google": "AIza-user"}):
        rejected = describe_model_error(provider_error("openai", "bad key", 401), GEMINI)
        assert "Update it in Settings" in rejected
        assert "isn't allowed" in describe_model_error(
            provider_error("google.genai", "PERMISSION_DENIED"), GEMINI
        )
    assert "isn't available" in describe_model_error(provider_error("openai", "x", 404), GEMINI)
    assert "didn't respond in time" in describe_model_error(TimeoutError(), GEMINI)


def test_googles_400_for_a_bad_key_counts_as_a_rejected_key():
    error = provider_error(
        "google.genai.errors", "400 Bad Request. API key not valid. Please pass a valid API key."
    )
    with user_api_keys({"google": "AIza-user"}):
        assert "rejected your API key" in describe_model_error(error, GEMINI)


def test_other_errors_are_left_alone():
    assert describe_model_error(ValueError("404 row not found"), GEMINI) is None
    assert describe_model_error(provider_error("openai", "something odd", 500), GEMINI) is None


def test_stream_and_invoke_report_the_message(test_client, mock_agent):
    async def failing_stream(**kwargs):
        raise QUOTA
        yield

    mock_agent.astream = failing_stream
    mock_agent.ainvoke.side_effect = QUOTA
    with patch.object(settings, "DEFAULT_MODEL", DeepseekModelName.DEEPSEEK_V4_FLASH):
        stream = test_client.post("/stream", json={"message": "hi", "stream_tokens": False})
        invoke = test_client.post("/invoke", json={"message": "hi"})
    assert "limiting requests" in stream.text and "[DONE]" in stream.text
    assert invoke.status_code == 502 and "limiting requests" in invoke.json()["detail"]

"""Model-written chat titles: tidy, only for new chats, and never over a title the user set."""

from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage

from core.settings import settings
from db.chats import claim_chat, get_chat, rename_chat
from db.engine import async_session_scope
from schema.models import FakeModelName, OpenAIModelName
from service import titles


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Trip Planning Ideas."', "Trip Planning Ideas"),
        ("Title: **Tokyo weather**\n\nThis title fits because…", "Tokyo weather"),
        ("   ", None),
        ("word " * 30, "word " * 11 + "word"),
    ],
)
def test_clean_title(raw, expected):
    assert titles.clean_title(raw) == expected


async def _new_chat(thread_id: str, message: str = "how do I plan a weekend in Kyoto?") -> str:
    async with async_session_scope() as session:
        chat = await claim_chat(session, thread_id, "u1", "chatbot", message)
        return chat.title


async def _title(thread_id: str) -> str | None:
    async with async_session_scope() as session:
        return (await get_chat(session, thread_id)).title


def _model(reply: str):
    return patch.object(titles, "get_model", return_value=FakeListChatModel(responses=[reply]))


@pytest.mark.asyncio
async def test_generated_title_replaces_the_placeholder():
    placeholder = await _new_chat("title-1")
    with _model('"Weekend in Kyoto."'):
        await titles._name_chat(
            "title-1", placeholder, "how do I plan…", OpenAIModelName.GPT_5_MINI
        )
    assert await _title("title-1") == "Weekend in Kyoto"


@pytest.mark.asyncio
async def test_keeps_a_title_the_user_set_meanwhile():
    placeholder = await _new_chat("title-2")
    async with async_session_scope() as session:
        await rename_chat(session, "title-2", "u1", "chatbot", "My Kyoto trip")
    with _model("Weekend in Kyoto"):
        await titles._name_chat(
            "title-2", placeholder, "how do I plan…", OpenAIModelName.GPT_5_MINI
        )
    assert await _title("title-2") == "My Kyoto trip"


@pytest.mark.asyncio
async def test_model_errors_keep_the_placeholder():
    placeholder = await _new_chat("title-3")
    with patch.object(titles, "get_model", side_effect=RuntimeError("no key")):
        await titles._name_chat(
            "title-3", placeholder, "how do I plan…", OpenAIModelName.GPT_5_MINI
        )
    assert await _title("title-3") == placeholder


def test_only_new_chats_are_named(test_client, mock_agent):
    mock_agent.ainvoke.return_value = [("values", {"messages": [AIMessage(content="ok")]})]
    body = {"message": "hello there", "thread_id": "title-4", "user_id": "u1"}
    with (
        patch.object(settings, "GENERATE_CHAT_TITLES", True),
        patch("service.service.name_chat_later") as name_later,
    ):
        test_client.post("/invoke", json=body)
        test_client.post("/invoke", json={**body, "message": "and again"})
    name_later.assert_called_once()
    assert name_later.call_args.args[:3] == ("title-4", "hello there", "hello there")


def test_skipped_when_off_or_for_the_fake_model():
    with patch.object(titles.asyncio, "create_task") as create_task:
        with patch.object(settings, "GENERATE_CHAT_TITLES", False):
            titles.name_chat_later("t", "p", "hi", OpenAIModelName.GPT_5_MINI)
        with patch.object(settings, "GENERATE_CHAT_TITLES", True):
            titles.name_chat_later("t", "p", "hi", FakeModelName.FAKE)
    create_task.assert_not_called()

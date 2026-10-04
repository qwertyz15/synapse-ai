from unittest.mock import patch

import pytest
from langchain_openai import OpenAIEmbeddings
from langchain_voyageai import VoyageAIEmbeddings
from pydantic import SecretStr

from core.embeddings import get_embeddings
from core.settings import EmbeddingProvider


def _patch_settings(**overrides):
    values = {
        "EMBEDDING_PROVIDER": EmbeddingProvider.OPENAI,
        "EMBEDDING_MODEL": None,
        "OPENAI_API_KEY": None,
        "VOYAGE_API_KEY": None,
        **overrides,
    }
    return patch.multiple("core.embeddings.settings", **values)


def test_openai_embeddings_default_model():
    with _patch_settings(OPENAI_API_KEY=SecretStr("test_key")):
        embeddings = get_embeddings()
    assert isinstance(embeddings, OpenAIEmbeddings)
    assert embeddings.model == "text-embedding-ada-002"


def test_openai_embeddings_custom_model():
    with _patch_settings(
        OPENAI_API_KEY=SecretStr("test_key"), EMBEDDING_MODEL="text-embedding-3-small"
    ):
        embeddings = get_embeddings()
    assert embeddings.model == "text-embedding-3-small"


def test_openai_embeddings_requires_key():
    with _patch_settings(), pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_embeddings()


def test_voyage_embeddings_default_model():
    with _patch_settings(
        EMBEDDING_PROVIDER=EmbeddingProvider.VOYAGE, VOYAGE_API_KEY=SecretStr("test_key")
    ):
        embeddings = get_embeddings()
    assert isinstance(embeddings, VoyageAIEmbeddings)
    assert embeddings.model == "voyage-4"


def test_voyage_embeddings_custom_model():
    with _patch_settings(
        EMBEDDING_PROVIDER=EmbeddingProvider.VOYAGE,
        VOYAGE_API_KEY=SecretStr("test_key"),
        EMBEDDING_MODEL="voyage-4-lite",
    ):
        embeddings = get_embeddings()
    assert embeddings.model == "voyage-4-lite"


def test_voyage_embeddings_requires_key():
    with (
        _patch_settings(EMBEDDING_PROVIDER=EmbeddingProvider.VOYAGE),
        pytest.raises(ValueError, match="VOYAGE_API_KEY"),
    ):
        get_embeddings()

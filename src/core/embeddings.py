"""Embedding model shared by the Chroma build script and the RAG search tool.

Both must use the same provider and model, or searches return garbage or fail on a
vector dimension mismatch. Rebuild the database after changing either setting.
"""

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_voyageai import VoyageAIEmbeddings

from core.settings import EmbeddingProvider, settings

# Matches OpenAIEmbeddings' implicit default, so existing databases keep working.
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-ada-002"
DEFAULT_VOYAGE_EMBEDDING_MODEL = "voyage-4"


def get_embeddings() -> Embeddings:
    match settings.EMBEDDING_PROVIDER:
        case EmbeddingProvider.OPENAI:
            if not settings.OPENAI_API_KEY:
                raise ValueError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY to be set")
            return OpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL or DEFAULT_OPENAI_EMBEDDING_MODEL,
                api_key=settings.OPENAI_API_KEY,
            )
        case EmbeddingProvider.VOYAGE:
            if not settings.VOYAGE_API_KEY:
                raise ValueError("EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY to be set")
            return VoyageAIEmbeddings(
                model=settings.EMBEDDING_MODEL or DEFAULT_VOYAGE_EMBEDDING_MODEL,
                api_key=settings.VOYAGE_API_KEY,
            )

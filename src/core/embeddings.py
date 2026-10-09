"""Embedding model shared by ingestion and the RAG search tool.

Both must use the same provider and model, or searches return garbage or fail on a
vector dimension mismatch. The library is re-embedded automatically when either changes.
"""

from langchain_core.embeddings import Embeddings

from core.settings import EmbeddingProvider, settings

# Matches OpenAIEmbeddings' implicit default, so existing databases keep working.
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-ada-002"
DEFAULT_VOYAGE_EMBEDDING_MODEL = "voyage-4"


def embedding_signature() -> str:
    """Identifies the configured provider and model, to detect when an index must be rebuilt."""
    match settings.EMBEDDING_PROVIDER:
        case EmbeddingProvider.OPENAI:
            model = settings.EMBEDDING_MODEL or DEFAULT_OPENAI_EMBEDDING_MODEL
        case EmbeddingProvider.VOYAGE:
            model = settings.EMBEDDING_MODEL or DEFAULT_VOYAGE_EMBEDDING_MODEL
    return f"{settings.EMBEDDING_PROVIDER}:{model}"


def get_embeddings() -> Embeddings:
    match settings.EMBEDDING_PROVIDER:
        case EmbeddingProvider.OPENAI:
            if not settings.OPENAI_API_KEY:
                raise ValueError("EMBEDDING_PROVIDER=openai requires OPENAI_API_KEY to be set")
            # Imported here so the ingestion worker loads only the configured provider.
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL or DEFAULT_OPENAI_EMBEDDING_MODEL,
                api_key=settings.OPENAI_API_KEY,
            )
        case EmbeddingProvider.VOYAGE:
            if not settings.VOYAGE_API_KEY:
                raise ValueError("EMBEDDING_PROVIDER=voyage requires VOYAGE_API_KEY to be set")
            from langchain_voyageai import VoyageAIEmbeddings

            return VoyageAIEmbeddings(
                model=settings.EMBEDDING_MODEL or DEFAULT_VOYAGE_EMBEDDING_MODEL,
                api_key=settings.VOYAGE_API_KEY,
            )

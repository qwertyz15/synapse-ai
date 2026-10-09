"""Reranking search results with a cross-encoder model (Voyage AI), before they reach the assistant.

Search finds candidates fast (hybrid: meaning + keywords); the reranker reads the question and each
candidate together and orders them by how well they answer it. If reranking fails, the caller
keeps the search's own results, so a reranker outage never breaks document search.
"""

import logging
import time

from langchain_core.documents import Document

from core import settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 10

_client = None


def enabled() -> bool:
    return settings.RERANKER == "voyage" and settings.VOYAGE_API_KEY is not None


def _voyage():
    global _client
    if _client is None:
        import voyageai

        key = settings.VOYAGE_API_KEY.get_secret_value() if settings.VOYAGE_API_KEY else None
        _client = voyageai.Client(api_key=key, max_retries=1, timeout=TIMEOUT_S)
    return _client


def rerank(query: str, documents: list[Document], top_k: int) -> list[Document] | None:
    """The top_k documents, best first, each with a `rerank_score`; None if reranking failed."""
    if len(documents) <= 1:
        return documents[:top_k]
    started = time.monotonic()
    try:
        result = _voyage().rerank(
            query,
            [d.page_content for d in documents],
            model=settings.RERANK_MODEL,
            top_k=top_k,
            truncation=True,
        )
    except Exception as e:
        logger.warning(f"Reranking failed, keeping the search results: {type(e).__name__}: {e}")
        return None
    logger.info(f"Reranked {len(documents)} passages in {time.monotonic() - started:.2f}s")
    ranked = []
    for item in result.results:
        doc = documents[item.index]
        ranked.append(
            Document(
                id=doc.id,
                page_content=doc.page_content,
                metadata={**doc.metadata, "rerank_score": round(item.relevance_score, 4)},
            )
        )
    return ranked

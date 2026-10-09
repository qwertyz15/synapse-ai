from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from pydantic import SecretStr

from agents import tools
from core import settings
from ingestion import rerank


class FakeVoyage:
    """Scores a passage by how many query words it contains."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def rerank(self, query, documents, model, top_k, truncation):
        self.calls.append({"documents": documents, "model": model, "top_k": top_k})
        if self.fail:
            raise TimeoutError("Voyage timed out")
        words = set(query.lower().split())
        scored = sorted(
            (
                (len(words & set(d.lower().split())) / len(words), i)
                for i, d in enumerate(documents)
            ),
            reverse=True,
        )
        results = [SimpleNamespace(index=i, relevance_score=s) for s, i in scored[:top_k]]
        return SimpleNamespace(results=results)


@pytest.fixture
def voyage(monkeypatch):
    fake = FakeVoyage()
    monkeypatch.setattr(settings, "RERANKER", "voyage")
    monkeypatch.setattr(settings, "VOYAGE_API_KEY", SecretStr("test"))
    monkeypatch.setattr(rerank, "_client", fake)
    return fake


def _docs(*texts: str, source: str = "a.txt") -> list[Document]:
    return [Document(page_content=t, metadata={"source": source}) for t in texts]


def test_disabled_without_reranker_or_key(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER", "voyage")
    assert not rerank.enabled()
    monkeypatch.setattr(settings, "RERANKER", "none")
    monkeypatch.setattr(settings, "VOYAGE_API_KEY", SecretStr("test"))
    assert not rerank.enabled()


def test_orders_by_relevance_and_keeps_top_k(voyage):
    docs = _docs("lunch menu", "annual leave is 20 days", "leave policy for annual leave")
    ranked = rerank.rerank("annual leave policy", docs, top_k=2)
    assert ranked is not None
    assert [d.page_content for d in ranked] == [
        "leave policy for annual leave",
        "annual leave is 20 days",
    ]
    assert ranked[0].metadata == {"source": "a.txt", "rerank_score": 1.0}
    assert voyage.calls[0]["model"] == settings.RERANK_MODEL
    assert "rerank_score" not in docs[2].metadata


def test_failure_returns_none(voyage):
    voyage.fail = True
    assert rerank.rerank("leave", _docs("one", "two"), top_k=1) is None


def _sources(monkeypatch, chat, mine, shared):
    asked = []

    def found(docs):
        def search(*args):
            asked.append(tools._k())
            return docs

        return search

    monkeypatch.setattr(tools, "_chat_documents", found(chat))
    monkeypatch.setattr(tools, "_user_library_documents", found(mine))
    monkeypatch.setattr(tools, "_library_documents", found(shared))
    return asked


def test_search_tool_reranks_candidates_from_every_source(monkeypatch, voyage):
    monkeypatch.setattr(settings, "RERANK_TOP_K", 2)
    chat = _docs(*(f"chat note {i}" for i in range(8)), source="chat.txt")
    shared = _docs("annual leave policy: 20 days", source="hr.pdf")
    asked = _sources(monkeypatch, chat, [], shared)

    result = tools.database_search_func("annual leave policy", {})

    assert asked == [settings.RERANK_CANDIDATES] * 3
    assert len(voyage.calls[0]["documents"]) == 9
    assert result.startswith("[Source: hr.pdf]\nannual leave policy")
    assert result.count("[Source:") == 2


def test_search_tool_falls_back_to_each_sources_best(monkeypatch, voyage):
    voyage.fail = True
    chat = _docs(*(f"chat note {i}" for i in range(8)), source="chat.txt")
    shared = _docs("annual leave policy", source="hr.pdf")
    _sources(monkeypatch, chat, [], shared)

    result = tools.database_search_func("annual leave policy", {})

    assert result.count("[Source: chat.txt]") == tools.SEARCH_K
    assert "[Source: hr.pdf]" in result


def test_search_tool_without_reranker_asks_for_five(monkeypatch):
    asked = _sources(monkeypatch, _docs("x"), [], [])
    assert tools.database_search_func("x", {}) == "[Source: a.txt]\nx"
    assert asked == [tools.SEARCH_K] * 3

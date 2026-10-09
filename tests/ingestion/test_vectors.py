"""The Qdrant-backed vector store, in embedded mode."""

from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from core.settings import settings
from ingestion import vectors
from ingestion.vectors import VectorStore

EMBEDDINGS = DeterministicFakeEmbedding(size=16)


@pytest.fixture
def store(tmp_path):
    with (
        patch.object(settings, "QDRANT_PATH", str(tmp_path / "qdrant")),
        patch.object(settings, "QDRANT_URL", None),
    ):
        yield VectorStore("test", EMBEDDINGS)


def _chunk(chunk_id, text, **meta):
    return Document(id=chunk_id, page_content=text, metadata=meta)


def test_add_search_count_and_delete_with_filters(store):
    assert store.count() == 0 and store.search("anything") == []
    store.add(
        [
            _chunk("a#0", "apples are red", user_id="u1", source="a.txt"),
            _chunk("a#1", "apples are sweet", user_id="u1", source="a.txt"),
            _chunk("b#0", "bananas are yellow", user_id="u2", source="b.txt"),
        ]
    )
    assert store.count() == 3 and store.count({"user_id": "u1"}) == 2
    found = store.search("bananas are yellow", k=5, match={"user_id": "u2"})
    assert [d.page_content for d in found] == ["bananas are yellow"]
    assert found[0].id == "b#0" and found[0].metadata == {"user_id": "u2", "source": "b.txt"}

    store.add([_chunk("a#0", "apples, edited", user_id="u1", source="a.txt")])
    assert store.count() == 3

    store.delete({"user_id": "u1", "source": "a.txt"})
    assert store.count() == 1


def test_set_fields_skips_excluded_values_and_lists_metadata(store):
    store.add(
        [
            _chunk("x#0", "x", user_id="anon", source="keep.txt"),
            _chunk("y#0", "y", user_id="anon", source="move.txt"),
        ]
    )
    moved = store.set_fields(
        {"user_id": "anon"}, {"user_id": "acct"}, exclude={"source": ["keep.txt"]}
    )
    assert moved == 1
    owners = {m["source"]: m["user_id"] for m in store.metadatas()}
    assert owners == {"keep.txt": "anon", "move.txt": "acct"}


def test_writes_in_batches_and_reset(store):
    with patch.object(vectors, "WRITE_BATCH", 2):
        store.add([_chunk(f"c#{i}", f"text {i}") for i in range(5)])
    assert store.count() == 5 and len(store.metadatas()) == 5
    store.reset()
    assert not store.exists() and store.count() == 0

"""The Qdrant-backed vector store, in embedded mode."""

from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from core.settings import settings
from ingestion import vectors
from ingestion.vectors import VectorStore
from ingestion.vectors import _point_id as vectors_point_id

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


def _invoices(store, n=40):
    store.add(
        [
            _chunk(
                f"inv#{i}",
                f"Invoice INV-{1000 + i} for office supplies, paid in full.",
                user_id="u1",
            )
            for i in range(n)
        ]
    )


@pytest.mark.parametrize("fusion", ["dbsf", "rrf"])
def test_hybrid_search_finds_exact_codes_the_embeddings_miss(store, fusion):
    # The fake embeddings are random, so only the keyword side can find the right invoice.
    _invoices(store)
    with patch.object(settings, "HYBRID_FUSION", fusion):
        for code in (1003, 1027, 1039):
            hits = store.search(f"Which invoice is INV-{code}?", k=5)
            assert f"inv#{code - 1000}" in [h.id for h in hits]
    with patch.object(settings, "HYBRID_SEARCH", False):
        found = sum(
            f"inv#{i}" in [h.id for h in store.search(f"Which invoice is INV-{1000 + i}?", k=5)]
            for i in range(40)
        )
    assert found < 20


def test_filters_apply_to_both_sides(store):
    _invoices(store)
    store.add([_chunk("other#0", "Invoice INV-1027 copy", user_id="u2")])
    hits = store.search("INV-1027", k=5, match={"user_id": "u1"})
    assert "inv#27" in [h.id for h in hits] and all(h.metadata["user_id"] == "u1" for h in hits)


def test_semantic_only_when_hybrid_is_off(store):
    _invoices(store, n=5)
    with patch.object(settings, "HYBRID_SEARCH", False):
        assert len(store.search("INV-1003", k=3)) == 3


def test_collections_from_before_hybrid_search_are_upgraded_in_place(store):
    from qdrant_client import models

    client = store.client
    client.create_collection(
        "legacy", vectors_config=models.VectorParams(size=16, distance=models.Distance.COSINE)
    )
    texts = [f"Contract clause {i}: notice period is {i} weeks" for i in range(10)]
    vectors = EMBEDDINGS.embed_documents(texts)
    client.upsert(
        "legacy",
        points=[
            models.PointStruct(
                id=vectors_point_id(f"c#{i}"),
                vector=vectors[i],
                payload={"page_content": t, "chunk_id": f"c#{i}", "doc_id": "contract.pdf"},
            )
            for i, t in enumerate(texts)
        ],
    )

    legacy = VectorStore("legacy", EMBEDDINGS)
    assert "c#7" in [h.id for h in legacy.search("clause 7", k=3)]
    info = client.get_collection("legacy")
    assert "bm25" in (info.config.params.sparse_vectors or {}) and legacy.count() == 10
    [point] = client.retrieve("legacy", ids=[vectors_point_id("c#3")], with_vectors=True)
    # Cosine collections store vectors normalized to unit length.
    norm = sum(x * x for x in vectors[3]) ** 0.5
    assert point.vector[""] == pytest.approx([x / norm for x in vectors[3]], abs=1e-5)
    assert not client.collection_exists("legacy__upgrade")

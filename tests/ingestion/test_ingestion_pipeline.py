import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from ingestion import run_ingestion
from ingestion.index import open_vectorstore

SIGNATURE = "fake:test-model"


@pytest.fixture
def embeddings():
    return DeterministicFakeEmbedding(size=16)


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "a.txt").write_text("Alpha document. " * 20)
    (folder / "b.md").write_text("# Beta\n" + "Beta content. " * 20)
    return folder


def _ingest(source, db, embeddings, **kwargs):
    kwargs.setdefault("signature", SIGNATURE)
    return run_ingestion(
        source, db, embeddings=embeddings, chunk_size=100, chunk_overlap=0, **kwargs
    )


def _chunk_ids(db, embeddings, doc_id):
    return open_vectorstore(db, embeddings).get(where={"doc_id": doc_id})["ids"]


def test_incremental_ingestion_lifecycle(tmp_path, source, embeddings):
    db = tmp_path / "db"

    first = _ingest(source, db, embeddings)
    assert first.full_rebuild
    assert sorted(first.new) == ["a.txt", "b.md"]
    assert first.chunks_written > 0

    second = _ingest(source, db, embeddings)
    assert not second.full_rebuild
    assert sorted(second.unchanged) == ["a.txt", "b.md"]
    assert second.new == second.updated == second.deleted == []
    assert second.chunks_written == 0

    old_ids = _chunk_ids(db, embeddings, "a.txt")
    (source / "a.txt").write_text("Short now.")
    third = _ingest(source, db, embeddings)
    assert third.updated == ["a.txt"]
    new_ids = _chunk_ids(db, embeddings, "a.txt")
    assert len(new_ids) == 1 < len(old_ids)

    (source / "b.md").unlink()
    fourth = _ingest(source, db, embeddings)
    assert fourth.deleted == ["b.md"]
    assert _chunk_ids(db, embeddings, "b.md") == []


def test_embedding_change_triggers_full_rebuild(tmp_path, source, embeddings):
    db = tmp_path / "db"
    _ingest(source, db, embeddings)

    report = _ingest(source, db, embeddings, signature="fake:other-model")

    assert report.full_rebuild
    assert sorted(report.new) == ["a.txt", "b.md"]
    assert len(open_vectorstore(db, embeddings).get()["ids"]) == report.chunks_written


def test_failed_document_is_isolated_and_retried(tmp_path, source, embeddings):
    db = tmp_path / "db"
    (source / "broken.pdf").write_bytes(b"not a pdf")

    first = _ingest(source, db, embeddings)
    assert "broken.pdf" in first.failed
    assert sorted(first.new) == ["a.txt", "b.md"]

    second = _ingest(source, db, embeddings)
    assert "broken.pdf" in second.failed
    assert second.chunks_written == 0


def test_dry_run_writes_nothing(tmp_path, source, embeddings):
    db = tmp_path / "db"

    report = _ingest(source, db, embeddings, dry_run=True)

    assert report.dry_run
    assert sorted(report.new) == ["a.txt", "b.md"]
    assert report.chunks_written == 0
    assert not db.exists()

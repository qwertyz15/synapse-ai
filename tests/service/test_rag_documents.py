from functools import partial
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding

from client import AgentClient, AgentClientError
from ingestion import run_ingestion
from service import app


@pytest.fixture
def rag_env(tmp_path):
    data_dir = tmp_path / "data"
    fake_ingestion = partial(
        run_ingestion,
        embeddings=DeterministicFakeEmbedding(size=16),
        signature="fake:test",
        chunk_size=100,
        chunk_overlap=0,
    )
    with (
        patch("service.rag.settings.RAG_DATA_DIR", str(data_dir)),
        patch("service.rag.settings.CHROMA_DB_PATH", str(tmp_path / "db")),
        patch("service.rag.run_ingestion", fake_ingestion),
    ):
        yield data_dir


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, *files):
    return client.post("/rag/documents", files=[("files", f) for f in files])


def test_list_documents_empty_without_database(client, rag_env):
    response = client.get("/rag/documents")
    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_upload_list_replace_and_delete(client, rag_env):
    response = _upload(client, ("a.txt", b"Alpha " * 50), ("b.md", b"# Beta\nBeta text"))
    assert response.status_code == 200
    assert sorted(response.json()["new"]) == ["a.txt", "b.md"]
    assert (rag_env / "a.txt").exists()

    listed = client.get("/rag/documents").json()["documents"]
    assert [d["doc_id"] for d in listed] == ["a.txt", "b.md"]
    assert all(d["chunk_count"] > 0 for d in listed)

    replaced = _upload(client, ("a.txt", b"Changed"))
    assert replaced.json()["updated"] == ["a.txt"]

    deleted = client.delete("/rag/documents/b.md")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == ["b.md"]
    assert not (rag_env / "b.md").exists()
    assert [d["doc_id"] for d in client.get("/rag/documents").json()["documents"]] == ["a.txt"]


def test_upload_rejects_unsupported_and_hidden_files(client, rag_env):
    response = _upload(client, ("tool.exe", b"MZ"), (".env.txt", b"secret"))
    body = response.json()
    assert set(body["rejected"]) == {"tool.exe", ".env.txt"}
    assert body["new"] == []
    assert not (rag_env / "tool.exe").exists()


def test_upload_strips_directories_from_filename(client, rag_env):
    response = _upload(client, ("../../escape.txt", b"text"))
    assert response.json()["new"] == ["escape.txt"]
    assert (rag_env / "escape.txt").exists()
    assert not (rag_env.parent.parent / "escape.txt").exists()


def test_upload_rejects_oversized_file(client, rag_env):
    with patch("service.rag.MAX_UPLOAD_BYTES", 10):
        response = _upload(client, ("big.txt", b"x" * 11))
    assert "big.txt" in response.json()["rejected"]


def test_delete_rejects_path_outside_data_dir(client, rag_env):
    response = client.delete("/rag/documents/%2E%2E/secret.txt")
    assert response.status_code == 400


def test_delete_unknown_document_returns_404(client, rag_env):
    assert client.delete("/rag/documents/missing.txt").status_code == 404


def test_missing_embedding_config_returns_503(client, rag_env):
    with patch(
        "service.rag.run_ingestion", side_effect=ValueError("requires VOYAGE_API_KEY to be set")
    ):
        response = _upload(client, ("a.txt", b"text"))
    assert response.status_code == 503
    assert "VOYAGE_API_KEY" in response.json()["detail"]


def test_client_upload_surfaces_service_detail(client, rag_env):
    def post(url, **kwargs):
        return client.post(url.replace("http://test", ""), **kwargs)

    agent_client = AgentClient(base_url="http://test", get_info=False)
    with (
        patch("client.client.httpx.post", post),
        patch("service.rag.run_ingestion", side_effect=ValueError("requires VOYAGE_API_KEY")),
        pytest.raises(AgentClientError, match="requires VOYAGE_API_KEY"),
    ):
        agent_client.upload_documents([("a.txt", b"text")])

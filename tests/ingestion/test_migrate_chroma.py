"""Copying old Chroma collections into Qdrant keeps text, metadata and vectors."""

import chromadb
from langchain_core.embeddings import DeterministicFakeEmbedding

from ingestion.index import COLLECTION_NAME, open_vectorstore
from ingestion.migrate_chroma import migrate
from ingestion.user_library import USER_LIBRARY_COLLECTION, open_user_library

EMBEDDINGS = DeterministicFakeEmbedding(size=8)


def test_copies_collections_without_re_embedding_and_can_run_again(tmp_path):
    chroma = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    texts = ["Leave policy: 20 days.", "Remote work: two days a week."]
    library = chroma.create_collection(COLLECTION_NAME)
    library.add(
        ids=["handbook.pdf#0", "handbook.pdf#1"],
        documents=texts,
        embeddings=EMBEDDINGS.embed_documents(texts),
        metadatas=[{"doc_id": "handbook.pdf", "source": "handbook.pdf", "page": i} for i in (1, 2)],
    )
    mine = chroma.create_collection(USER_LIBRARY_COLLECTION)
    mine.add(
        ids=["user/u1/plan.txt#0"],
        documents=["Bluebird plan."],
        embeddings=EMBEDDINGS.embed_documents(["Bluebird plan."]),
        metadatas=[{"user_id": "u1", "source": "plan.txt", "scope": "user"}],
    )

    assert migrate(tmp_path / "chroma", dry_run=True) == {
        COLLECTION_NAME: 2,
        USER_LIBRARY_COLLECTION: 1,
    }
    assert not open_vectorstore().exists()

    assert migrate(tmp_path / "chroma") == {COLLECTION_NAME: 2, USER_LIBRARY_COLLECTION: 1}
    migrate(tmp_path / "chroma")
    assert open_vectorstore().count() == 2

    [hit] = open_vectorstore(EMBEDDINGS).search("Leave policy: 20 days.", k=1)
    assert hit.page_content == "Leave policy: 20 days." and hit.metadata["page"] == 1
    assert hit.id == "handbook.pdf#0"
    [mine_hit] = open_user_library(EMBEDDINGS).search(
        "Bluebird plan.", k=1, match={"user_id": "u1"}
    )
    assert mine_hit.page_content == "Bluebird plan."


def test_missing_folder_is_nothing_to_do(tmp_path):
    assert migrate(tmp_path / "nope") == {}

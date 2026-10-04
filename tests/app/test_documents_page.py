from streamlit.testing.v1 import AppTest

from client import AgentClientError
from schema import IngestionResult, RagDocument, RagDocuments

PAGE = "../../src/pages/Documents.py"


def _doc(doc_id: str) -> RagDocument:
    return RagDocument(
        doc_id=doc_id, file_type="pdf", chunk_count=3, ingested_at="2026-10-04T12:00:00+00:00"
    )


def test_documents_page_empty(mock_agent_client):
    mock_agent_client.list_documents.return_value = RagDocuments(documents=[])

    at = AppTest.from_file(PAGE).run()

    assert not at.exception
    assert at.title[0].value == "📄 Documents"
    assert "No documents yet" in at.info[0].value
    assert at.button[0].label == "Upload and index"
    assert at.button[0].disabled


def test_documents_page_lists_and_deletes(mock_agent_client):
    mock_agent_client.list_documents.return_value = RagDocuments(
        documents=[_doc("handbook.pdf"), _doc("policies/leave.pdf")]
    )
    mock_agent_client.delete_document.return_value = IngestionResult(deleted=["handbook.pdf"])

    at = AppTest.from_file(PAGE).run()
    assert [m.value for m in at.markdown if m.value.startswith("**")] == [
        "**handbook.pdf**",
        "**policies/leave.pdf**",
    ]
    assert "3 chunks · 2026-10-04 12:00 UTC" in at.caption[1].value

    at.button(key="delete_handbook.pdf").click().run()

    mock_agent_client.delete_document.assert_called_once_with("handbook.pdf")
    assert "Removed **handbook.pdf**" in at.info[0].value
    assert not at.exception


def test_documents_page_shows_service_error(mock_agent_client):
    mock_agent_client.list_documents.side_effect = AgentClientError("Service unavailable")

    at = AppTest.from_file(PAGE).run()

    assert "Couldn't load documents: Service unavailable" in at.error[0].value

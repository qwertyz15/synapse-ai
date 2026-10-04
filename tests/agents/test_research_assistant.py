from unittest.mock import patch

from agents import research_assistant as ra


def _rows(*doc_ids):
    return [(doc_id, "pdf", 1, "2026-10-04T00:00:00+00:00") for doc_id in doc_ids]


def test_document_search_tool_is_available():
    assert "DocumentSearch" in {t.name for t in ra.tools}


def test_instructions_list_uploaded_documents():
    with patch.object(ra, "list_indexed_documents", return_value=_rows("handbook.pdf", "a.md")):
        instructions = ra.build_instructions()
    assert "searchable with DocumentSearch: handbook.pdf, a.md." in instructions


def test_instructions_without_documents():
    with patch.object(ra, "list_indexed_documents", return_value=[]):
        assert "hasn't uploaded any documents" in ra.build_instructions()


def test_instructions_cap_long_document_lists():
    doc_ids = [f"doc{i}.pdf" for i in range(ra.MAX_LISTED_DOCUMENTS + 5)]
    with patch.object(ra, "list_indexed_documents", return_value=_rows(*doc_ids)):
        instructions = ra.build_instructions()
    assert "doc0.pdf" in instructions
    assert f"doc{ra.MAX_LISTED_DOCUMENTS}.pdf" not in instructions
    assert "and 5 more" in instructions


def test_instructions_survive_unreadable_index():
    with patch.object(ra, "list_indexed_documents", side_effect=OSError("disk error")):
        assert "unavailable right now" in ra.build_instructions()

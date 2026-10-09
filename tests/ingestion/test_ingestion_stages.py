import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import DeterministicFakeEmbedding

from agents.tools import database_search_func, format_contexts
from ingestion import parsers
from ingestion.changes import detect_changes
from ingestion.chunking import chunk_document
from ingestion.cleaning import clean_pages, clean_text
from ingestion.index import open_vectorstore
from ingestion.loader import LocalFolderConnector, hash_file
from ingestion.models import ParsedPage, SourceDocument
from ingestion.parsers import parse

SAMPLE_PDF = Path(__file__).parents[2] / "data" / "AcmeTech_Employee_Handbook.pdf"


def _doc(doc_id: str, content_hash: str = "h") -> SourceDocument:
    return SourceDocument(
        doc_id=doc_id, path=Path(doc_id), file_type="txt", content_hash=content_hash
    )


def test_loader_filters_extensions_and_uses_relative_ids(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub" / "b.MD").write_text("b")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")

    docs = list(LocalFolderConnector(tmp_path).iter_documents())

    assert [d.doc_id for d in docs] == ["a.txt", "sub/b.MD"]
    assert [d.file_type for d in docs] == ["txt", "md"]
    assert docs[0].content_hash == hash_file(tmp_path / "a.txt")


def test_detect_changes_covers_all_states():
    current = [_doc("same", "1"), _doc("edited", "new-hash"), _doc("added", "3")]
    indexed = {"same": "1", "edited": "old-hash", "removed": "4"}

    changes = detect_changes(current, indexed)

    assert [d.doc_id for d in changes.new] == ["added"]
    assert [d.doc_id for d in changes.updated] == ["edited"]
    assert [d.doc_id for d in changes.unchanged] == ["same"]
    assert changes.deleted == ["removed"]


def test_parse_text_and_pdf_pages(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("# Title\nBody", encoding="utf-8")
    assert parse(SourceDocument("notes.md", md, "md", "h")) == [ParsedPage("# Title\nBody")]

    pages = parse(SourceDocument("handbook.pdf", SAMPLE_PDF, "pdf", "h"))
    assert [p.page for p in pages] == list(range(1, len(pages) + 1))
    assert any(p.text.strip() for p in pages)


def test_clean_text_normalizes_whitespace_and_hyphenation():
    assert clean_text("Employ-\nee  hand\tbook\r\n\n\n\nNext   ") == "Employee hand book\n\nNext"


def test_clean_pages_drops_empty_pages():
    pages = [ParsedPage("  \n ", 1), ParsedPage(" text ", 2)]
    assert clean_pages(pages) == [ParsedPage("text", 2)]


def test_chunk_document_ids_and_metadata():
    doc = SourceDocument("docs/guide.pdf", Path("docs/guide.pdf"), "pdf", "abc")
    pages = [ParsedPage("one " * 30, 1), ParsedPage("two " * 30, 2)]

    chunks = chunk_document(doc, pages, chunk_size=50, chunk_overlap=0)

    assert [c.id for c in chunks] == [f"docs/guide.pdf#{i}" for i in range(len(chunks))]
    assert {c.metadata["page"] for c in chunks} == {1, 2}
    first = chunks[0].metadata
    assert first["doc_id"] == "docs/guide.pdf"
    assert first["source"] == "guide.pdf"
    assert first["content_hash"] == "abc"
    assert first["acl"] == "public"


def test_chunk_document_omits_missing_page():
    doc = SourceDocument("a.txt", Path("a.txt"), "txt", "h")
    chunks = chunk_document(doc, [ParsedPage("hello")], chunk_size=100, chunk_overlap=0)
    assert "page" not in chunks[0].metadata


def test_search_with_nothing_indexed_says_so_and_creates_nothing():
    with patch("agents.tools.get_embeddings", return_value=DeterministicFakeEmbedding(size=8)):
        found = database_search_func(
            "leave policy", {"configurable": {"thread_id": "t", "user_id": "u"}}
        )
    assert found == "No matching passages found in the uploaded documents."
    assert not open_vectorstore().exists()


def test_format_contexts_cites_source_and_page():
    docs = [
        Document(page_content="Leave policy", metadata={"source": "handbook.pdf", "page": 4}),
        Document(page_content="Notes", metadata={"source": "notes.md"}),
    ]
    assert format_contexts(docs) == (
        "[Source: handbook.pdf, page 4]\nLeave policy\n\n[Source: notes.md]\nNotes"
    )


def test_untrusted_parse_matches_in_process_parse():
    doc = SourceDocument("handbook.pdf", SAMPLE_PDF, "pdf", "h")
    assert parsers.parse_untrusted(doc) == parse(doc)


def test_untrusted_parse_times_out(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("hello")
    with pytest.raises(ValueError, match="Took longer than"):
        parsers.parse_untrusted(SourceDocument("a.txt", path, "txt", "h"), timeout_s=0.001)


def test_untrusted_parse_reports_parser_errors(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(ValueError):
        parsers.parse_untrusted(SourceDocument("broken.pdf", path, "pdf", "h"))


def test_rejects_docx_that_unpacks_too_large(tmp_path):
    path = tmp_path / "big.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "x" * 1000)
    with patch.object(parsers, "MAX_DOCX_UNCOMPRESSED_BYTES", 100):
        with pytest.raises(ValueError, match="Unpacks to more than"):
            parse(SourceDocument("big.docx", path, "docx", "h"))


def test_rejects_pdf_with_too_many_pages():
    with patch.object(parsers, "MAX_PDF_PAGES", 1):
        with pytest.raises(ValueError, match="More than 1 pages"):
            parse(SourceDocument("handbook.pdf", SAMPLE_PDF, "pdf", "h"))

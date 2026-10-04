import docx2txt
from pypdf import PdfReader

from ingestion.models import ParsedPage, SourceDocument


def parse(doc: SourceDocument) -> list[ParsedPage]:
    match doc.file_type:
        case "pdf":
            reader = PdfReader(doc.path)
            return [
                ParsedPage(text=page.extract_text() or "", page=number)
                for number, page in enumerate(reader.pages, start=1)
            ]
        case "docx":
            return [ParsedPage(text=docx2txt.process(str(doc.path)) or "")]
        case "txt" | "md":
            return [ParsedPage(text=doc.path.read_text(encoding="utf-8", errors="replace"))]
        case _:
            raise ValueError(f"Unsupported file type: {doc.file_type}")

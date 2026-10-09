import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import docx2txt
from pypdf import PdfReader

from ingestion.models import ParsedPage, SourceDocument

MAX_PDF_PAGES = 2000
MAX_DOCX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
UNTRUSTED_PARSE_TIMEOUT_S = 60
UNTRUSTED_PARSE_MEMORY_BYTES = 1024 * 1024 * 1024


def parse(doc: SourceDocument) -> list[ParsedPage]:
    match doc.file_type:
        case "pdf":
            reader = PdfReader(doc.path)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ValueError(f"More than {MAX_PDF_PAGES} pages")
            return [
                ParsedPage(text=page.extract_text() or "", page=number)
                for number, page in enumerate(reader.pages, start=1)
            ]
        case "docx":
            # A .docx is a zip; check the unpacked size before docx2txt inflates it.
            with zipfile.ZipFile(doc.path) as archive:
                if sum(i.file_size for i in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ValueError("Unpacks to more than 200 MB")
            return [ParsedPage(text=docx2txt.process(str(doc.path)) or "")]
        case "txt" | "md":
            return [ParsedPage(text=doc.path.read_text(encoding="utf-8", errors="replace"))]
        case _:
            raise ValueError(f"Unsupported file type: {doc.file_type}")


def parse_untrusted(
    doc: SourceDocument,
    timeout_s: float = UNTRUSTED_PARSE_TIMEOUT_S,
    memory_bytes: int = UNTRUSTED_PARSE_MEMORY_BYTES,
) -> list[ParsedPage]:
    """Parse an uploaded file in a separate process with a time and memory limit.

    A crafted PDF or DOCX can make the parser spin or allocate without bound; this keeps that
    from stalling or killing the service. Raises ValueError when the file can't be read.
    """
    src_dir = str(Path(__file__).resolve().parents[1])
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(filter(None, [src_dir, os.environ.get("PYTHONPATH")])),
    }
    command = [
        sys.executable,
        "-m",
        "ingestion.parse_worker",
        str(doc.path),
        doc.file_type,
        str(memory_bytes),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout_s, env=env, check=False
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"Took longer than {timeout_s:g} seconds to read")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("The reader stopped unexpectedly")
    if "error" in output:
        raise ValueError(output["error"])
    return [ParsedPage(text=text, page=page) for text, page in output["pages"]]

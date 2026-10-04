import re
import unicodedata

from ingestion.models import ParsedPage

_HYPHENATED_BREAK = re.compile(r"(\w)-\n(\w)")
_INLINE_WHITESPACE = re.compile(r"[ \t\f\v]+")
_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHENATED_BREAK.sub(r"\1\2", text)
    text = _INLINE_WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _EXTRA_BLANK_LINES.sub("\n\n", text).strip()


def clean_pages(pages: list[ParsedPage]) -> list[ParsedPage]:
    cleaned = (ParsedPage(text=clean_text(p.text), page=p.page) for p in pages)
    return [p for p in cleaned if p.text]

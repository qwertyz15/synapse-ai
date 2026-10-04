from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    path: Path
    file_type: str
    content_hash: str


@dataclass(frozen=True)
class ParsedPage:
    text: str
    page: int | None = None


@dataclass
class ChangeSet:
    new: list[SourceDocument] = field(default_factory=list)
    updated: list[SourceDocument] = field(default_factory=list)
    unchanged: list[SourceDocument] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


@dataclass
class IngestionReport:
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    chunks_written: int = 0
    full_rebuild: bool = False
    dry_run: bool = False

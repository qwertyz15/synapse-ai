"""Incremental RAG ingestion: load → detect changes → parse → clean → chunk → embed → index.

Each stage lives in its own module so it can be swapped out (e.g. a remote connector or a queue).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ingestion.models import IngestionReport
    from ingestion.pipeline import run_ingestion

__all__ = ["IngestionReport", "run_ingestion"]


def __getattr__(name: str):
    # Lazy so the upload parse worker can import the parsers without loading the whole pipeline.
    if name == "run_ingestion":
        from ingestion.pipeline import run_ingestion

        return run_ingestion
    if name == "IngestionReport":
        from ingestion.models import IngestionReport

        return IngestionReport
    raise AttributeError(f"module 'ingestion' has no attribute {name!r}")

"""Incremental RAG ingestion: load → detect changes → parse → clean → chunk → embed → index.

Each stage lives in its own module so it can be swapped out (e.g. a remote connector or a queue).
"""

from ingestion.models import IngestionReport
from ingestion.pipeline import run_ingestion

__all__ = ["IngestionReport", "run_ingestion"]

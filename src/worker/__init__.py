"""Celery worker for background indexing. Start it with: celery -A worker worker"""

from worker.celery_app import app

__all__ = ["app"]

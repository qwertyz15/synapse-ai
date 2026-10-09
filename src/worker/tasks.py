import random

from celery.exceptions import SoftTimeLimitExceeded

from core import settings
from ingestion.jobs import RetryLater, give_up, run_job
from worker.celery_app import app


@app.task(bind=True, name="synapse.index_upload", max_retries=settings.JOB_MAX_RETRIES)
def index_upload(self, job_id: str) -> str:
    """Index one uploaded file; temporary provider errors are retried with backoff and jitter."""
    try:
        return run_job(job_id).status
    except RetryLater as e:
        if self.request.retries >= self.max_retries:
            give_up(job_id, f"Gave up after {self.max_retries + 1} tries: {e}")
            return "failed"
        delay = min(300, 15 * 2**self.request.retries) + random.randint(0, 10)
        raise self.retry(countdown=delay)
    except SoftTimeLimitExceeded:
        give_up(job_id, f"Indexing took longer than {settings.JOB_TIME_LIMIT_S} seconds")
        return "failed"


def enqueue(job_id: str) -> None:
    index_upload.delay(job_id)

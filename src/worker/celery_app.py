"""Celery app for indexing uploads in the background, set up to stay within a fixed amount of memory.

It imports only settings, the database and ingestion code, never the agents or model providers.
"""

from celery import Celery

from core import settings

app = Celery("synapse", broker=settings.REDIS_URL or "memory://", include=["worker.tasks"])
app.conf.update(
    task_default_queue="ingestion",
    # Status lives in the ingestion_jobs table, so nothing is written back to Redis.
    task_ignore_result=True,
    # A job whose worker dies goes back to the queue instead of being lost.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Take one job at a time, so a process holds at most one file's chunks in memory.
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.WORKER_CONCURRENCY,
    # Replace worker processes regularly, and after a job that grew them past the memory budget.
    worker_max_tasks_per_child=settings.WORKER_MAX_TASKS_PER_CHILD,
    worker_max_memory_per_child=settings.WORKER_MAX_MEMORY_MB * 1024,
    task_time_limit=settings.JOB_TIME_LIMIT_S,
    task_soft_time_limit=max(30, settings.JOB_TIME_LIMIT_S - 30),
    # Must outlast the longest job plus retry delays, or Redis hands an unfinished job to another worker.
    broker_transport_options={"visibility_timeout": max(3600, settings.JOB_TIME_LIMIT_S * 4)},
    broker_connection_retry_on_startup=True,
    worker_send_task_events=False,
)

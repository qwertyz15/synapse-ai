"""The Celery indexing task: retries temporary failures with backoff, then gives up cleanly."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest
from celery.exceptions import Retry, SoftTimeLimitExceeded

from ingestion.jobs import Outcome, RetryLater
from worker import tasks

task = tasks.index_upload


@contextmanager
def attempt(number: int):
    """Run as Celery would on the given retry (0 = first try)."""
    task.push_request(retries=number)
    try:
        yield
    finally:
        task.pop_request()


@pytest.fixture
def give_up():
    with patch.object(tasks, "give_up") as mock:
        yield mock


def test_runs_the_job(give_up):
    with attempt(0), patch.object(tasks, "run_job", return_value=Outcome(status="ready")) as run:
        assert task.run("job-1") == "ready"
    run.assert_called_once_with("job-1")
    give_up.assert_not_called()


@pytest.mark.parametrize(("number", "base"), [(0, 15), (1, 30), (2, 60)])
def test_temporary_failures_are_retried_with_growing_delays(give_up, number, base):
    with (
        attempt(number),
        patch.object(tasks, "run_job", side_effect=RetryLater("429")),
        patch.object(task, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        task.run("job-1")
    delay = retry.call_args.kwargs["countdown"]
    assert base <= delay <= base + 10
    give_up.assert_not_called()


def test_gives_up_after_the_last_retry(give_up):
    with (
        attempt(task.max_retries),
        patch.object(tasks, "run_job", side_effect=RetryLater("still 429")),
    ):
        assert task.run("job-1") == "failed"
    assert "Gave up after 4 tries: still 429" in give_up.call_args.args[1]


def test_time_limit_marks_the_job_failed(give_up):
    with attempt(0), patch.object(tasks, "run_job", side_effect=SoftTimeLimitExceeded()):
        assert task.run("job-1") == "failed"
    assert "took longer than" in give_up.call_args.args[1]


def test_enqueue_sends_only_the_job_id():
    with patch.object(task, "delay", Mock()) as delay:
        tasks.enqueue("job-9")
    delay.assert_called_once_with("job-9")

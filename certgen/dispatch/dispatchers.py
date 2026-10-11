"""How a job gets run: in a background thread pool, or inline for tests.

The dispatcher only carries a job id. It is a trigger, not a queue: the database
holds the real state, so losing the in-memory executor (restart, crash) loses no
work. Startup recovery re-submits every unfinished job.
"""

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Protocol

logger = logging.getLogger(__name__)

JobRunnerFunction = Callable[[uuid.UUID], None]


class Dispatcher(Protocol):
    def start(self) -> None: ...

    def submit(self, job_id: uuid.UUID) -> None: ...

    def shutdown(self) -> None: ...


class InlineDispatcher:
    """Runs the job synchronously inside submit(). Deterministic, so tests can assert
    on final state straight after the POST returns."""

    def __init__(self, run_job: JobRunnerFunction) -> None:
        self._run_job = run_job

    def start(self) -> None:
        return None

    def submit(self, job_id: uuid.UUID) -> None:
        self._run_job(job_id)

    def shutdown(self) -> None:
        return None


class ThreadPoolDispatcher:
    """Runs each job on a worker thread. One task per job; the task walks that job's
    pending certificates in chunks. Several jobs run concurrently up to pool_size."""

    def __init__(self, run_job: JobRunnerFunction, pool_size: int) -> None:
        self._run_job = run_job
        self._pool_size = pool_size
        self._executor: ThreadPoolExecutor | None = None

    def start(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=self._pool_size, thread_name_prefix="certgen-worker"
        )
        logger.info("thread pool dispatcher started pool_size=%d", self._pool_size)

    def submit(self, job_id: uuid.UUID) -> None:
        if self._executor is None:
            raise RuntimeError("Dispatcher not started; call start() in the app lifespan.")
        future = self._executor.submit(self._run_job, job_id)
        future.add_done_callback(lambda done: self._log_crash(job_id, done))

    def shutdown(self) -> None:
        if self._executor is not None:
            # wait=True lets in-flight certificates finish. Anything not yet started
            # stays pending in the database and is resumed on the next startup.
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    @staticmethod
    def _log_crash(job_id: uuid.UUID, future: Future[None]) -> None:
        # Without this, an exception escaping a worker thread would vanish silently.
        if not future.cancelled() and future.exception() is not None:
            logger.error("job runner crashed job_id=%s", job_id, exc_info=future.exception())

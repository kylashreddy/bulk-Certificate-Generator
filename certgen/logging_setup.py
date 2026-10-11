"""Structured (key=value) logging with job/certificate context.

Context is held in contextvars so that every log line emitted while processing a
certificate carries its job_id and certificate_id without passing them around.
Contextvars are per-thread, which suits the thread-pool dispatcher.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)
_certificate_id: ContextVar[str | None] = ContextVar("certificate_id", default=None)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id.get() or "-"
        record.certificate_id = _certificate_id.get() or "-"
        return True


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())
    handler.setFormatter(
        logging.Formatter(
            "ts=%(asctime)s level=%(levelname)s logger=%(name)s "
            "job_id=%(job_id)s certificate_id=%(certificate_id)s msg=%(message)s"
        )
    )
    root = logging.getLogger("certgen")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


@contextmanager
def job_log_context(job_id: object) -> Iterator[None]:
    token = _job_id.set(str(job_id))
    try:
        yield
    finally:
        _job_id.reset(token)


@contextmanager
def certificate_log_context(certificate_id: object) -> Iterator[None]:
    token = _certificate_id.set(str(certificate_id))
    try:
        yield
    finally:
        _certificate_id.reset(token)

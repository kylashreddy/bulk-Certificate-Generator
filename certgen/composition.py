"""Composition root: the one place that decides which implementations are used.

Production gets ReportLab + local disk + a thread pool. Tests pass their own
renderer/storage/sleep here, so production code needs no test hooks at all.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from certgen.config import DispatcherKind, Settings
from certgen.db.session import build_engine, build_session_factory
from certgen.dispatch.dispatchers import Dispatcher, InlineDispatcher, ThreadPoolDispatcher
from certgen.rendering.protocol import CertificateRenderer
from certgen.rendering.security_print import SecurityPrintRenderer
from certgen.services.certificate_issuing import IssuingDependencies
from certgen.services.job_runner import run_job
from certgen.storage.local_disk import LocalDiskStorage
from certgen.storage.protocol import CertificateStorage


@dataclass(frozen=True)
class AppServices:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    storage: CertificateStorage
    dispatcher: Dispatcher


def build_app_services(
    settings: Settings,
    *,
    renderer: CertificateRenderer | None = None,
    storage: CertificateStorage | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AppServices:
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    storage = storage or LocalDiskStorage(settings.storage_dir)
    issuing = IssuingDependencies(
        session_factory=session_factory,
        renderer=renderer or SecurityPrintRenderer(),
        storage=storage,
        public_base_url=settings.public_base_url,
        max_attempts=settings.max_render_attempts,
        backoff_seconds=settings.retry_backoff_seconds,
        sleep=sleep,
    )
    run = partial(run_job, deps=issuing, chunk_size=settings.processing_chunk_size)
    dispatcher: Dispatcher
    if settings.dispatcher == DispatcherKind.INLINE:
        dispatcher = InlineDispatcher(run)
    else:
        dispatcher = ThreadPoolDispatcher(run, settings.worker_pool_size)
    return AppServices(settings, engine, session_factory, storage, dispatcher)

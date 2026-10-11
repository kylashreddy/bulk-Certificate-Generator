"""Drive one job from queued to a final status.

The loop asks the database "which rows of this job are still pending?" in chunks,
rather than iterating an in-memory list. That makes the runner restartable: after
a crash, running it again simply picks up whatever is still pending.
"""

import logging
import uuid
from collections.abc import Iterator

from sqlalchemy import select

from certgen.db.base import utc_now
from certgen.db.session import session_scope
from certgen.domain.statuses import CertificateStatus, JobStatus, transition_job
from certgen.logging_setup import job_log_context
from certgen.models import Certificate, CertificateJob
from certgen.services.certificate_issuing import IssuingDependencies, issue_certificate
from certgen.services.job_progress import final_job_status, load_job_progress

logger = logging.getLogger(__name__)


def run_job(job_id: uuid.UUID, deps: IssuingDependencies, chunk_size: int) -> None:
    with job_log_context(job_id):
        if not _mark_running(job_id, deps):
            return
        for certificate_ids in _pending_chunks(job_id, deps, chunk_size):
            for certificate_id in certificate_ids:
                issue_certificate(certificate_id, deps)
        _finalise(job_id, deps)


def _mark_running(job_id: uuid.UUID, deps: IssuingDependencies) -> bool:
    """Return False if there is nothing to do (unknown or already finished job)."""
    with session_scope(deps.session_factory) as session:
        job = session.get(CertificateJob, job_id)
        if job is None:
            logger.error("job not found; nothing to run")
            return False
        if job.status == JobStatus.QUEUED:
            transition_job(job, JobStatus.RUNNING)
            job.started_at = job.started_at or utc_now()
            logger.info("job started")
            return True
        # RUNNING means we are resuming after a restart; anything else is finished.
        return job.status == JobStatus.RUNNING


def _pending_chunks(
    job_id: uuid.UUID, deps: IssuingDependencies, chunk_size: int
) -> Iterator[list[uuid.UUID]]:
    """Yield lists of pending certificate ids until none are left.

    Each chunk is a fresh query, so rows claimed by another worker or reset by
    recovery are seen correctly. Rows that end up failed/issued drop out of the
    query, which guarantees the loop terminates.
    """
    while True:
        with session_scope(deps.session_factory) as session:
            certificate_ids = list(
                session.scalars(
                    select(Certificate.id)
                    .where(
                        Certificate.job_id == job_id,
                        Certificate.status == CertificateStatus.PENDING,
                    )
                    .order_by(Certificate.position)
                    .limit(chunk_size)
                )
            )
        if not certificate_ids:
            return
        yield certificate_ids


def _finalise(job_id: uuid.UUID, deps: IssuingDependencies) -> None:
    with session_scope(deps.session_factory) as session:
        job = session.get_one(CertificateJob, job_id)
        if job.status != JobStatus.RUNNING:
            # Another runner for the same job (e.g. after recovery) got here first.
            return
        progress = load_job_progress(session, job_id)
        if progress.unfinished:
            # Rows still "rendering" belong to a runner that died mid-way (for example
            # the database dropped during _record_outcome). Startup recovery owns them.
            logger.warning("job left running with %d unfinished rows", progress.unfinished)
            return
        final_status = final_job_status(progress)
        transition_job(job, final_status)
        job.finished_at = utc_now()
        logger.info(
            "job finished status=%s issued=%d failed=%d rejected=%d",
            final_status.value,
            progress.issued,
            progress.failed,
            progress.rejected,
        )

"""Crash recovery, run once at startup before the API accepts requests.

If the process died mid-render, some rows are stuck in "rendering" with no worker
behind them. They are reset to "pending" (the render was never recorded, so it is
safe to redo it; storage writes are atomic and idempotent per serial), and every
job that is not finished is handed back to the dispatcher.
"""

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from certgen.db.base import utc_now
from certgen.domain.statuses import CertificateStatus, JobStatus, check_certificate_transition
from certgen.models import Certificate, CertificateJob

logger = logging.getLogger(__name__)


def recover_interrupted_work(session: Session) -> list[uuid.UUID]:
    """Reset stuck rows and return the ids of jobs that need to be (re)dispatched."""
    check_certificate_transition(CertificateStatus.RENDERING, CertificateStatus.PENDING)
    reset_count = session.execute(
        update(Certificate)
        .where(Certificate.status == CertificateStatus.RENDERING)
        .values(status=CertificateStatus.PENDING, updated_at=utc_now())
    ).rowcount
    unfinished_job_ids = list(
        session.scalars(
            select(CertificateJob.id)
            .where(CertificateJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
            .order_by(CertificateJob.created_at)
        )
    )
    session.commit()
    if reset_count or unfinished_job_ids:
        logger.info(
            "startup recovery reset_rendering=%d jobs_to_resume=%d",
            reset_count,
            len(unfinished_job_ids),
        )
    return unfinished_job_ids

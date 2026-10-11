"""Progress and final status, both derived from the certificate rows.

There are no stored counters on the job. Counters updated by several worker threads
can drift (a lost update, a crash between two writes); a GROUP BY over the rows is
always exactly right, and the (job_id, status) index keeps it cheap.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from certgen.domain.statuses import CertificateStatus, JobStatus
from certgen.models import Certificate


@dataclass(frozen=True)
class JobProgress:
    pending: int
    rendering: int
    issued: int
    failed: int
    rejected: int

    @property
    def total(self) -> int:
        return self.pending + self.rendering + self.issued + self.failed + self.rejected

    @property
    def unfinished(self) -> int:
        return self.pending + self.rendering

    @property
    def percent_complete(self) -> float:
        if self.total == 0:
            return 100.0
        return round(100 * (self.total - self.unfinished) / self.total, 1)


def load_job_progress(session: Session, job_id: uuid.UUID) -> JobProgress:
    counts = dict(
        session.execute(
            select(Certificate.status, func.count())
            .where(Certificate.job_id == job_id)
            .group_by(Certificate.status)
        ).all()
    )
    return JobProgress(
        pending=counts.get(CertificateStatus.PENDING, 0),
        rendering=counts.get(CertificateStatus.RENDERING, 0),
        issued=counts.get(CertificateStatus.ISSUED, 0),
        failed=counts.get(CertificateStatus.FAILED, 0),
        rejected=counts.get(CertificateStatus.REJECTED, 0),
    )


def final_job_status(progress: JobProgress) -> JobStatus:
    """Only meaningful once nothing is pending or rendering.

    "Nothing issued" is `failed` even when every row was merely rejected: from the
    client's point of view the job produced no certificates.
    """
    if progress.issued == progress.total:
        return JobStatus.COMPLETED
    if progress.issued > 0:
        return JobStatus.COMPLETED_WITH_ERRORS
    return JobStatus.FAILED

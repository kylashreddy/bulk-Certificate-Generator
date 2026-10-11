"""Re-queue a finished job's failed certificates.

Only `failed` rows are retried. `rejected` rows failed validation, and retrying
them would fail identically, so the client has to submit corrected data instead.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from certgen.domain.errors import JobNotRetryable
from certgen.domain.statuses import (
    CertificateStatus,
    JobStatus,
    transition_certificate,
    transition_job,
)
from certgen.models import Certificate
from certgen.services.certificate_queries import get_job


def requeue_failed_certificates(session: Session, job_id: uuid.UUID) -> int:
    job = get_job(session, job_id)
    if job.status not in (JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED):
        raise JobNotRetryable(
            f"Only finished jobs with failures can be retried; this job is {job.status.value}."
        )
    failed_rows = list(
        session.scalars(
            select(Certificate).where(
                Certificate.job_id == job_id, Certificate.status == CertificateStatus.FAILED
            )
        )
    )
    if not failed_rows:
        raise JobNotRetryable("This job has no failed certificates to retry.")
    for certificate in failed_rows:
        transition_certificate(certificate, CertificateStatus.PENDING)
        certificate.error_code = None
        certificate.error_message = None
    transition_job(job, JobStatus.QUEUED)
    job.finished_at = None
    session.commit()
    return len(failed_rows)

"""Turn domain objects into response schemas. URLs are built here because they are
an HTTP concern the services should not know about."""

import uuid

from certgen.domain.statuses import CertificateStatus
from certgen.models import Certificate, CertificateJob
from certgen.schemas.certificate_views import CertificateDetail, CertificateSummary
from certgen.schemas.job_responses import (
    CertificateDetailsView,
    JobCreated,
    JobLinks,
    JobProgressView,
    JobStatusView,
    RejectedRecipient,
)
from certgen.services.job_creation import JobCreationResult
from certgen.services.job_progress import JobProgress

API_PREFIX = "/api/v1"


def job_url(job_id: uuid.UUID) -> str:
    return f"{API_PREFIX}/jobs/{job_id}"


def pdf_url(certificate: Certificate) -> str | None:
    if certificate.status != CertificateStatus.ISSUED:
        return None
    return f"{API_PREFIX}/certificates/{certificate.id}/pdf"


def present_job_created(result: JobCreationResult) -> JobCreated:
    return JobCreated(
        job_id=result.job.id,
        status=result.job.status,
        status_url=job_url(result.job.id),
        accepted_count=result.accepted_count,
        rejected_count=len(result.rejected),
        rejected=[
            RejectedRecipient(
                position=row.position,
                recipient_name=row.raw_name,
                recipient_email=row.raw_email,
                error_code=row.error_code,
                error_message=row.error_message,
            )
            for row in result.rejected
        ],
    )


def present_job_status(job: CertificateJob, progress: JobProgress) -> JobStatusView:
    return JobStatusView(
        job_id=job.id,
        status=job.status,
        certificate=CertificateDetailsView(
            title=job.title,
            achievement_line=job.achievement_line,
            certificate_kind=job.certificate_kind,
            issued_on=job.issued_on,
            issuer_name=job.issuer_name,
            signatory_name=job.signatory_name,
            signatory_title=job.signatory_title,
        ),
        progress=JobProgressView(
            total=progress.total,
            pending=progress.pending,
            rendering=progress.rendering,
            issued=progress.issued,
            failed=progress.failed,
            rejected=progress.rejected,
            percent_complete=progress.percent_complete,
        ),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        links=JobLinks(
            certificates=f"{job_url(job.id)}/certificates",
            archive=f"{job_url(job.id)}/archive.zip",
        ),
    )


def present_certificate_summary(certificate: Certificate) -> CertificateSummary:
    return CertificateSummary(
        certificate_id=certificate.id,
        position=certificate.position,
        recipient_name=certificate.recipient_name,
        recipient_email=certificate.recipient_email,
        status=certificate.status,
        serial=certificate.serial,
        error_code=certificate.error_code,
        error_message=certificate.error_message,
        download_url=pdf_url(certificate),
    )


def present_certificate_detail(certificate: Certificate) -> CertificateDetail:
    return CertificateDetail(
        **present_certificate_summary(certificate).model_dump(),
        job_id=certificate.job_id,
        verification_code=certificate.verification_code,
        attempts=certificate.attempts,
        issued_at=certificate.issued_at,
    )

"""Create a job and all its certificate rows in a single transaction.

Writing every row up front (including rejected ones) means the database alone
describes the whole job. A crash after the commit loses nothing: startup recovery
finds the pending rows and finishes them.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from certgen.domain.errors import IdempotencyKeyReused, InvalidRecipients, TooManyRecipients
from certgen.domain.serials import format_serial, new_serial_prefix, new_verification_code
from certgen.domain.statuses import CertificateStatus
from certgen.models import Certificate, CertificateJob
from certgen.schemas.job_requests import CreateJobRequest
from certgen.services.recipient_validation import (
    RecipientScreening,
    RejectedRecipientRow,
    screen_recipients,
)

logger = logging.getLogger(__name__)

# A serial-prefix collision is ~1 in a million per pair of jobs; a few retries make
# a repeated collision practically impossible.
MAX_PREFIX_ATTEMPTS = 5


@dataclass(frozen=True)
class JobCreationResult:
    job: CertificateJob
    accepted_count: int
    rejected: list[RejectedRecipientRow]
    # True when an Idempotency-Key matched an existing job and nothing new was created.
    replayed: bool


def create_job(
    session: Session,
    request: CreateJobRequest,
    *,
    idempotency_key: str | None,
    strict: bool,
    max_recipients: int,
) -> JobCreationResult:
    if len(request.recipients) > max_recipients:
        raise TooManyRecipients(
            f"A job may contain at most {max_recipients} recipients; "
            f"received {len(request.recipients)}.",
            details=[{"location": "body.recipients", "message": f"max {max_recipients} items"}],
        )

    fingerprint = request_fingerprint(request)
    if idempotency_key:
        existing = _find_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return _replay(session, existing, fingerprint)

    screening = screen_recipients(request.recipients)
    if strict and screening.rejected:
        raise InvalidRecipients(
            f"{len(screening.rejected)} recipient(s) failed validation; strict mode "
            "refuses the whole request.",
            details=[_rejection_detail(row) for row in screening.rejected],
        )

    for _ in range(MAX_PREFIX_ATTEMPTS):
        job = _build_job(request, screening, idempotency_key, fingerprint)
        session.add(job)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            # Two possible causes: a concurrent request with the same Idempotency-Key
            # committed first (replay it), or a serial-prefix collision (try again).
            if idempotency_key:
                existing = _find_by_idempotency_key(session, idempotency_key)
                if existing is not None:
                    return _replay(session, existing, fingerprint)
            continue
        logger.info(
            "job created id=%s accepted=%d rejected=%d",
            job.id,
            len(screening.valid),
            len(screening.rejected),
        )
        return JobCreationResult(job, len(screening.valid), screening.rejected, replayed=False)

    raise RuntimeError("Could not allocate a unique serial prefix for the job.")


def request_fingerprint(request: CreateJobRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _find_by_idempotency_key(session: Session, idempotency_key: str) -> CertificateJob | None:
    return session.scalars(
        select(CertificateJob).where(CertificateJob.idempotency_key == idempotency_key)
    ).one_or_none()


def _replay(session: Session, job: CertificateJob, fingerprint: str) -> JobCreationResult:
    if job.request_fingerprint != fingerprint:
        raise IdempotencyKeyReused(
            "This Idempotency-Key was already used with a different request body.",
            details=[{"job_id": str(job.id)}],
        )
    rejected_rows = session.scalars(
        select(Certificate)
        .where(Certificate.job_id == job.id, Certificate.status == CertificateStatus.REJECTED)
        .order_by(Certificate.position)
    ).all()
    total = session.scalar(
        select(func.count()).select_from(Certificate).where(Certificate.job_id == job.id)
    )
    rejected = [
        RejectedRecipientRow(
            position=row.position,
            raw_name=row.recipient_name,
            raw_email=row.recipient_email,
            error_code=row.error_code or "",
            error_message=row.error_message or "",
        )
        for row in rejected_rows
    ]
    return JobCreationResult(job, (total or 0) - len(rejected), rejected, replayed=True)


def _build_job(
    request: CreateJobRequest,
    screening: RecipientScreening,
    idempotency_key: str | None,
    fingerprint: str,
) -> CertificateJob:
    details = request.certificate
    job = CertificateJob(
        id=uuid.uuid4(),
        title=details.title,
        achievement_line=details.achievement_line,
        certificate_kind=details.certificate_kind,
        issued_on=details.issued_on,
        issuer_name=details.issuer_name,
        signatory_name=details.signatory_name,
        signatory_title=details.signatory_title,
        serial_prefix=new_serial_prefix(),
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    pending_rows = [
        Certificate(
            position=recipient.position,
            recipient_name=recipient.name,
            recipient_email=recipient.email,
            status=CertificateStatus.PENDING,
            serial=format_serial(details.issued_on.year, job.serial_prefix, recipient.position),
            verification_code=new_verification_code(),
        )
        for recipient in screening.valid
    ]
    rejected_rows = [
        Certificate(
            position=row.position,
            recipient_name=row.raw_name,
            recipient_email=row.raw_email,
            status=CertificateStatus.REJECTED,
            error_code=row.error_code,
            error_message=row.error_message,
        )
        for row in screening.rejected
    ]
    job.certificates = sorted(pending_rows + rejected_rows, key=lambda row: row.position)
    return job


def _rejection_detail(row: RejectedRecipientRow) -> dict[str, object]:
    return {
        "position": row.position,
        "recipient_name": row.raw_name,
        "recipient_email": row.raw_email,
        "error_code": row.error_code,
        "error_message": row.error_message,
    }

"""Read-side queries for jobs and certificates. Routers call these; they never query."""

import base64
import binascii
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from certgen.domain.errors import (
    CertificateNotFound,
    CertificateNotIssued,
    InvalidCursor,
    JobNotFound,
    VerificationCodeNotFound,
)
from certgen.domain.statuses import CertificateStatus
from certgen.models import Certificate, CertificateJob
from certgen.storage.protocol import CertificateStorage


@dataclass(frozen=True)
class CertificatePageResult:
    certificates: list[Certificate]
    next_cursor: str | None


@dataclass(frozen=True)
class IssuedPdf:
    certificate: Certificate
    pdf_bytes: bytes


def get_job(session: Session, job_id: uuid.UUID) -> CertificateJob:
    job = session.get(CertificateJob, job_id)
    if job is None:
        raise JobNotFound(f"No job with id {job_id}.")
    return job


def get_certificate(session: Session, certificate_id: uuid.UUID) -> Certificate:
    certificate = session.get(Certificate, certificate_id)
    if certificate is None:
        raise CertificateNotFound(f"No certificate with id {certificate_id}.")
    return certificate


def list_job_certificates(
    session: Session,
    job_id: uuid.UUID,
    *,
    status: CertificateStatus | None,
    limit: int,
    cursor: str | None,
) -> CertificatePageResult:
    """Keyset pagination on position. Unlike OFFSET, it stays fast on page 500 and
    does not skip or repeat rows while workers are changing statuses."""
    get_job(session, job_id)
    query = select(Certificate).where(Certificate.job_id == job_id)
    if status is not None:
        query = query.where(Certificate.status == status)
    if cursor is not None:
        query = query.where(Certificate.position > decode_cursor(cursor))
    # Fetch one extra row to know whether another page exists without a COUNT.
    rows = list(session.scalars(query.order_by(Certificate.position).limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].position) if has_more else None
    return CertificatePageResult(page, next_cursor)


def encode_cursor(position: int) -> str:
    return base64.urlsafe_b64encode(str(position).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return int(base64.urlsafe_b64decode(padded.encode()).decode())
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursor("The pagination cursor is not valid.") from error


def load_issued_pdf(
    session: Session, storage: CertificateStorage, certificate_id: uuid.UUID
) -> IssuedPdf:
    certificate = get_certificate(session, certificate_id)
    if certificate.status != CertificateStatus.ISSUED or certificate.file_key is None:
        raise CertificateNotIssued(
            "This certificate has no PDF yet.",
            details=[{"status": certificate.status.value}],
        )
    return IssuedPdf(certificate, storage.read(certificate.file_key))


def find_issued_by_verification_code(
    session: Session, verification_code: str
) -> tuple[Certificate, CertificateJob]:
    certificate = session.scalars(
        select(Certificate).where(
            Certificate.verification_code == verification_code,
            Certificate.status == CertificateStatus.ISSUED,
        )
    ).one_or_none()
    if certificate is None:
        raise VerificationCodeNotFound("No issued certificate matches this verification code.")
    return certificate, get_job(session, certificate.job_id)

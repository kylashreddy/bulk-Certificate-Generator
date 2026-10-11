"""Response bodies for certificate endpoints."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from certgen.domain.statuses import CertificateStatus


class CertificateSummary(BaseModel):
    certificate_id: uuid.UUID
    position: int
    recipient_name: str
    recipient_email: str
    status: CertificateStatus
    serial: str | None
    error_code: str | None
    error_message: str | None
    download_url: str | None


class CertificateDetail(CertificateSummary):
    job_id: uuid.UUID
    verification_code: str | None
    attempts: int
    issued_at: datetime | None


class CertificatePage(BaseModel):
    items: list[CertificateSummary]
    next_cursor: str | None


class VerificationResult(BaseModel):
    valid: bool
    serial: str
    recipient_name: str
    title: str
    issuer_name: str
    issued_on: date

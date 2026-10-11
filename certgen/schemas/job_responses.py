"""Response bodies for job endpoints."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from certgen.domain.statuses import JobStatus
from certgen.models.job import CertificateKind


class RejectedRecipient(BaseModel):
    position: int
    recipient_name: str
    recipient_email: str
    error_code: str
    error_message: str


class JobCreated(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    status_url: str
    accepted_count: int
    rejected_count: int
    rejected: list[RejectedRecipient]


class CertificateDetailsView(BaseModel):
    title: str
    achievement_line: str
    certificate_kind: CertificateKind
    issued_on: date
    issuer_name: str
    signatory_name: str
    signatory_title: str


class JobProgressView(BaseModel):
    total: int
    pending: int
    rendering: int
    issued: int
    failed: int
    rejected: int
    percent_complete: float


class JobLinks(BaseModel):
    certificates: str
    archive: str


class JobStatusView(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    certificate: CertificateDetailsView
    progress: JobProgressView
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    links: JobLinks


class JobRetried(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    requeued_count: int

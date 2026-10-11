"""The two status machines, defined once and enforced on every change.

Any code that changes a status calls `transition_job` / `transition_certificate`.
An illegal move raises `InvalidTransition` instead of silently corrupting state,
which matters once several worker threads touch the same job.
"""

from enum import StrEnum
from typing import Protocol, TypeVar


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class CertificateStatus(StrEnum):
    REJECTED = "rejected"
    PENDING = "pending"
    RENDERING = "rendering"
    ISSUED = "issued"
    FAILED = "failed"


JOB_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED}
    ),
    # Only reachable through the explicit retry endpoint, which re-queues failed rows.
    JobStatus.COMPLETED_WITH_ERRORS: frozenset({JobStatus.QUEUED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.COMPLETED: frozenset(),
}

CERTIFICATE_TRANSITIONS: dict[CertificateStatus, frozenset[CertificateStatus]] = {
    CertificateStatus.REJECTED: frozenset(),
    CertificateStatus.PENDING: frozenset({CertificateStatus.RENDERING}),
    CertificateStatus.RENDERING: frozenset(
        {
            CertificateStatus.ISSUED,
            CertificateStatus.FAILED,
            # Startup recovery: a row left "rendering" by a crashed process is re-queued.
            CertificateStatus.PENDING,
        }
    ),
    CertificateStatus.ISSUED: frozenset(),
    # Only through the explicit retry endpoint.
    CertificateStatus.FAILED: frozenset({CertificateStatus.PENDING}),
}

TERMINAL_CERTIFICATE_STATUSES = frozenset(
    {CertificateStatus.REJECTED, CertificateStatus.ISSUED, CertificateStatus.FAILED}
)


class InvalidTransition(Exception):
    def __init__(self, entity: str, current: StrEnum, requested: StrEnum) -> None:
        super().__init__(f"{entity} cannot move from {current.value} to {requested.value}")
        self.current = current
        self.requested = requested


StatusT = TypeVar("StatusT", bound=StrEnum)


class _HasStatus(Protocol[StatusT]):
    status: StatusT


def _check(
    entity_name: str,
    current: StatusT,
    requested: StatusT,
    allowed: dict[StatusT, frozenset[StatusT]],
) -> None:
    if requested not in allowed[current]:
        raise InvalidTransition(entity_name, current, requested)


def transition_job(job: _HasStatus[JobStatus], requested: JobStatus) -> None:
    _check("Job", job.status, requested, JOB_TRANSITIONS)
    job.status = requested


def transition_certificate(
    certificate: _HasStatus[CertificateStatus], requested: CertificateStatus
) -> None:
    _check("Certificate", certificate.status, requested, CERTIFICATE_TRANSITIONS)
    certificate.status = requested


def check_certificate_transition(current: CertificateStatus, requested: CertificateStatus) -> None:
    """For bulk/conditional UPDATE statements that never load the row into Python."""
    _check("Certificate", current, requested, CERTIFICATE_TRANSITIONS)

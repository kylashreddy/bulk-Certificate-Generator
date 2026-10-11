"""Issue one certificate: claim -> render -> store -> record the outcome.

Failure isolation: everything that can go wrong for one recipient is caught here
and recorded on that recipient's row. Nothing propagates to the job loop, so one
bad certificate can never stop the others.

Retry policy:
- Transient errors (OSError: disk full, network share hiccup, timeout) are retried
  up to max_attempts with exponential backoff, because trying again may succeed.
- Anything else (bad data, a ReportLab error) is deterministic: the same input
  would fail the same way, so it fails immediately with RENDER_ERROR.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from certgen.db.base import utc_now
from certgen.db.session import session_scope
from certgen.domain.statuses import (
    CertificateStatus,
    check_certificate_transition,
    transition_certificate,
)
from certgen.logging_setup import certificate_log_context
from certgen.models import Certificate, CertificateJob
from certgen.rendering.protocol import CertificateRenderer, RenderContext
from certgen.storage.protocol import CertificateStorage

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS: tuple[type[Exception], ...] = (OSError,)


@dataclass(frozen=True)
class IssuingDependencies:
    session_factory: sessionmaker[Session]
    renderer: CertificateRenderer
    storage: CertificateStorage
    public_base_url: str
    max_attempts: int = 3
    backoff_seconds: float = 0.5
    # Injected so tests can verify the backoff schedule without actually sleeping.
    sleep: Callable[[float], None] = field(default=time.sleep)


@dataclass(frozen=True)
class _Outcome:
    attempts: int
    file_key: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def verification_url(public_base_url: str, verification_code: str) -> str:
    return f"{public_base_url.rstrip('/')}/api/v1/verify/{verification_code}"


def issue_certificate(certificate_id: uuid.UUID, deps: IssuingDependencies) -> None:
    with certificate_log_context(certificate_id):
        context = _claim(certificate_id, deps)
        if context is None:
            return
        job_id, render_context = context
        outcome = _render_and_store(job_id, render_context, deps)
        _record_outcome(certificate_id, outcome, deps)


def _claim(
    certificate_id: uuid.UUID, deps: IssuingDependencies
) -> tuple[uuid.UUID, RenderContext] | None:
    """Atomically move pending -> rendering. The WHERE status='pending' makes this a
    compare-and-set: if two workers race for the same row only one gets rowcount 1,
    so a certificate is never rendered twice. Works the same on SQLite and Postgres."""
    check_certificate_transition(CertificateStatus.PENDING, CertificateStatus.RENDERING)
    with session_scope(deps.session_factory) as session:
        claimed = session.execute(
            update(Certificate)
            .where(
                Certificate.id == certificate_id, Certificate.status == CertificateStatus.PENDING
            )
            .values(status=CertificateStatus.RENDERING, updated_at=utc_now())
        ).rowcount
        if claimed == 0:
            logger.info("certificate already claimed or no longer pending; skipping")
            return None
        certificate = session.get_one(Certificate, certificate_id)
        job = session.get_one(CertificateJob, certificate.job_id)
        return job.id, _render_context(job, certificate, deps.public_base_url)


def _render_context(
    job: CertificateJob, certificate: Certificate, public_base_url: str
) -> RenderContext:
    if certificate.serial is None or certificate.verification_code is None:
        raise ValueError("Only accepted (pending) certificates can be rendered.")
    return RenderContext(
        recipient_name=certificate.recipient_name,
        title=job.title,
        achievement_line=job.achievement_line,
        certificate_kind=job.certificate_kind.value,
        issued_on=job.issued_on,
        issuer_name=job.issuer_name,
        signatory_name=job.signatory_name,
        signatory_title=job.signatory_title,
        serial=certificate.serial,
        verification_url=verification_url(public_base_url, certificate.verification_code),
    )


def _render_and_store(
    job_id: uuid.UUID, context: RenderContext, deps: IssuingDependencies
) -> _Outcome:
    # No database session is held here: rendering is the slow part and must not
    # keep a connection (or, on SQLite, a write lock) open.
    for attempt in range(1, deps.max_attempts + 1):
        try:
            pdf_bytes = deps.renderer.render(context)
            file_key = deps.storage.save(job_id, context.serial, pdf_bytes)
            return _Outcome(attempts=attempt, file_key=file_key)
        except TRANSIENT_ERRORS as error:
            if attempt == deps.max_attempts:
                logger.error("transient error, attempts exhausted attempt=%d: %s", attempt, error)
                return _Outcome(attempt, error_code="TRANSIENT_ERROR", error_message=str(error))
            delay = deps.backoff_seconds * 2 ** (attempt - 1)
            logger.warning("transient error attempt=%d retry_in=%.2fs: %s", attempt, delay, error)
            deps.sleep(delay)
        except Exception as error:
            logger.exception("render failed attempt=%d", attempt)
            message = f"{type(error).__name__}: {error}"
            return _Outcome(attempt, error_code="RENDER_ERROR", error_message=message)
    raise AssertionError("unreachable: the loop always returns")


def _record_outcome(
    certificate_id: uuid.UUID, outcome: _Outcome, deps: IssuingDependencies
) -> None:
    with session_scope(deps.session_factory) as session:
        certificate = session.get_one(Certificate, certificate_id)
        certificate.attempts += outcome.attempts
        if outcome.file_key is not None:
            transition_certificate(certificate, CertificateStatus.ISSUED)
            certificate.file_key = outcome.file_key
            certificate.issued_at = utc_now()
            certificate.error_code = None
            certificate.error_message = None
            logger.info("certificate issued serial=%s", certificate.serial)
        else:
            transition_certificate(certificate, CertificateStatus.FAILED)
            certificate.error_code = outcome.error_code
            certificate.error_message = outcome.error_message
            logger.warning("certificate failed code=%s", outcome.error_code)

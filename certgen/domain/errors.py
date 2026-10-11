"""Domain exceptions. The API layer maps each one to an HTTP status and error code."""

from typing import Any


class DomainError(Exception):
    code = "DOMAIN_ERROR"

    def __init__(self, message: str, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class JobNotFound(DomainError):
    code = "JOB_NOT_FOUND"


class CertificateNotFound(DomainError):
    code = "CERTIFICATE_NOT_FOUND"


class CertificateNotIssued(DomainError):
    code = "CERTIFICATE_NOT_ISSUED"


class VerificationCodeNotFound(DomainError):
    code = "VERIFICATION_CODE_NOT_FOUND"


class TooManyRecipients(DomainError):
    # Same code as Pydantic failures: to the client it is just another request-shape error.
    code = "VALIDATION_ERROR"


class InvalidRecipients(DomainError):
    """Raised only in strict mode, where one bad row refuses the whole request."""

    code = "INVALID_RECIPIENTS"


class IdempotencyKeyReused(DomainError):
    code = "IDEMPOTENCY_KEY_REUSED"


class InvalidCursor(DomainError):
    code = "INVALID_CURSOR"


class JobNotRetryable(DomainError):
    code = "JOB_NOT_RETRYABLE"

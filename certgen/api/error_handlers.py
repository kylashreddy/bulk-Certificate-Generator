"""One error envelope for every failure: domain errors, FastAPI's own 404/405/422,
and unexpected exceptions. Clients parse a single shape:

    {"error": {"code": "...", "message": "...", "details": [...]}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from certgen.domain import errors
from certgen.schemas.error_envelope import ErrorBody, ErrorEnvelope

logger = logging.getLogger(__name__)

# HTTP status is an API concern, so the mapping lives here rather than on the exceptions.
DOMAIN_ERROR_STATUS: dict[type[errors.DomainError], int] = {
    errors.JobNotFound: 404,
    errors.CertificateNotFound: 404,
    errors.CertificateNotIssued: 404,
    errors.VerificationCodeNotFound: 404,
    errors.TooManyRecipients: 422,
    errors.InvalidRecipients: 422,
    errors.IdempotencyKeyReused: 409,
    errors.JobNotRetryable: 409,
    errors.InvalidCursor: 400,
}

HTTP_STATUS_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


def error_response(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


async def _handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, errors.DomainError)
    status_code = DOMAIN_ERROR_STATUS.get(type(error), 400)
    return error_response(status_code, error.code, error.message, error.details)


async def _handle_request_validation(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    details = [
        {
            "location": ".".join(str(part) for part in issue["loc"]),
            "message": issue["msg"],
        }
        for issue in error.errors()
    ]
    return error_response(422, "VALIDATION_ERROR", "Request failed validation.", details)


async def _handle_http_exception(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, StarletteHTTPException)
    code = HTTP_STATUS_CODES.get(error.status_code, "HTTP_ERROR")
    return error_response(error.status_code, code, str(error.detail))


async def _handle_unexpected(request: Request, error: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    # Never leak internals (stack traces, SQL) to the client.
    return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(errors.DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)

"""The single error shape returned for every non-2xx response."""

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = []


class ErrorEnvelope(BaseModel):
    error: ErrorBody

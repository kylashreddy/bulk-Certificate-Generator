"""Request body for POST /jobs.

Recipient fields are deliberately loose (any string, or missing). If `email` were
typed as EmailStr, Pydantic would reject the *entire* batch with a 422 because of
one bad address. Per-row rules live in services/recipient_validation.py instead,
so a bad row becomes a `rejected` certificate and the rest of the batch proceeds.
"""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from certgen.models.job import CertificateKind

RequiredText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CertificateDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[RequiredText, StringConstraints(max_length=200)]
    achievement_line: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""
    certificate_kind: CertificateKind = CertificateKind.COMPLETION
    issued_on: date = Field(default_factory=date.today)
    issuer_name: Annotated[RequiredText, StringConstraints(max_length=120)]
    signatory_name: Annotated[RequiredText, StringConstraints(max_length=120)]
    signatory_title: Annotated[RequiredText, StringConstraints(max_length=120)]


class RecipientInput(BaseModel):
    # Unknown per-recipient keys (e.g. "phone") are ignored rather than failing the batch.
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    email: str | None = None


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    certificate: CertificateDetails
    # The upper bound is a runtime setting, so it is checked in the service, not here.
    recipients: list[RecipientInput] = Field(min_length=1)

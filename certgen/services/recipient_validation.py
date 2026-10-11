"""Per-recipient validation and normalisation.

A failing row does not fail the request: it is stored as a `rejected` certificate
with a machine-readable reason. Rules run in a fixed order and the first failure
wins, so every rejected row carries exactly one error code.
"""

import re
import unicodedata
from dataclasses import dataclass

from email_validator import EmailNotValidError, validate_email

from certgen.schemas.job_requests import RecipientInput

MAX_NAME_LENGTH = 120
_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True)
class ValidRecipient:
    position: int
    name: str
    email: str


@dataclass(frozen=True)
class RejectedRecipientRow:
    position: int
    raw_name: str
    raw_email: str
    error_code: str
    error_message: str


@dataclass(frozen=True)
class RecipientScreening:
    valid: list[ValidRecipient]
    rejected: list[RejectedRecipientRow]


def normalise_name(raw_name: str) -> str:
    """NFC so "é" typed as e + combining accent equals the precomposed "é"
    (matters for fonts and duplicate detection); then trim and collapse spaces."""
    composed = unicodedata.normalize("NFC", raw_name)
    return _WHITESPACE_RUN.sub(" ", composed).strip()


def contains_control_characters(text: str) -> bool:
    # Unicode category "C*" covers control, format (e.g. zero-width) and unassigned code points.
    return any(unicodedata.category(character).startswith("C") for character in text)


def _name_problem(raw_name: str, name: str) -> tuple[str, str] | None:
    if not name:
        return "NAME_BLANK", "Recipient name is empty."
    # Checked on the raw value: whitespace collapsing would hide embedded tabs and newlines.
    if contains_control_characters(raw_name.strip()):
        return "NAME_CONTROL_CHARACTERS", "Recipient name contains control characters."
    if len(name) > MAX_NAME_LENGTH:
        return (
            "NAME_TOO_LONG",
            f"Recipient name is {len(name)} characters; the maximum is {MAX_NAME_LENGTH}.",
        )
    return None


def _normalised_email(raw_email: str) -> tuple[str | None, str | None]:
    """Return (normalised_email, error_message). DNS checks are off: validation must
    be fast and deterministic, and deliverability is the mail system's concern."""
    try:
        result = validate_email(raw_email.strip(), check_deliverability=False)
    except EmailNotValidError as error:
        return None, str(error)
    return result.normalized.lower(), None


def _screen_one(
    position: int, recipient: RecipientInput, first_position_by_email: dict[str, int]
) -> ValidRecipient | RejectedRecipientRow:
    raw_name = recipient.name or ""
    raw_email = recipient.email or ""

    name = normalise_name(raw_name)
    name_problem = _name_problem(raw_name, name)
    if name_problem:
        return RejectedRecipientRow(position, raw_name, raw_email, *name_problem)

    email, email_error = _normalised_email(raw_email)
    if email is None:
        message = email_error or "The email address is not valid."
        return RejectedRecipientRow(position, raw_name, raw_email, "EMAIL_INVALID", message)

    if email in first_position_by_email:
        message = f"Email already used by position {first_position_by_email[email]} in this job."
        return RejectedRecipientRow(position, raw_name, raw_email, "EMAIL_DUPLICATE", message)

    # Only accepted rows claim an email, so a rejected row never blocks a later valid one.
    first_position_by_email[email] = position
    return ValidRecipient(position, name, email)


def screen_recipients(recipients: list[RecipientInput]) -> RecipientScreening:
    valid: list[ValidRecipient] = []
    rejected: list[RejectedRecipientRow] = []
    first_position_by_email: dict[str, int] = {}

    for position, recipient in enumerate(recipients):
        outcome = _screen_one(position, recipient, first_position_by_email)
        if isinstance(outcome, ValidRecipient):
            valid.append(outcome)
        else:
            rejected.append(outcome)

    return RecipientScreening(valid=valid, rejected=rejected)

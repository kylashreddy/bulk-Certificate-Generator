"""Recipient-level validation: bad rows become `rejected`, good rows still get issued."""

import pytest
from fastapi.testclient import TestClient

from certgen.schemas.job_requests import RecipientInput
from certgen.services.recipient_validation import normalise_name, screen_recipients
from tests.conftest import JOBS_URL, job_payload


def screen_one(name: str | None, email: str | None) -> tuple[str | None, str]:
    """Return (error_code or None, normalised name or raw name)."""
    result = screen_recipients([RecipientInput(name=name, email=email)])
    if result.valid:
        return None, result.valid[0].name
    return result.rejected[0].error_code, result.rejected[0].raw_name


@pytest.mark.parametrize(
    ("name", "email", "expected_code"),
    [
        ("", "a@example.com", "NAME_BLANK"),
        ("   ", "a@example.com", "NAME_BLANK"),
        (None, "a@example.com", "NAME_BLANK"),
        ("A" * 121, "a@example.com", "NAME_TOO_LONG"),
        ("Ada\tLovelace", "a@example.com", "NAME_CONTROL_CHARACTERS"),
        ("Ada​Lovelace", "a@example.com", "NAME_CONTROL_CHARACTERS"),  # zero-width space
        ("Ada Lovelace", "not-an-email", "EMAIL_INVALID"),
        ("Ada Lovelace", "", "EMAIL_INVALID"),
        ("Ada Lovelace", None, "EMAIL_INVALID"),
        ("Ada Lovelace", "ada@", "EMAIL_INVALID"),
    ],
)
def test_invalid_recipient_is_rejected_with_reason(
    name: str | None, email: str | None, expected_code: str
) -> None:
    code, _ = screen_one(name, email)
    assert code == expected_code


def test_name_at_the_length_limit_is_accepted() -> None:
    code, _ = screen_one("A" * 120, "a@example.com")
    assert code is None


def test_names_are_normalised() -> None:
    decomposed = "José"  # "e" + combining acute accent
    assert normalise_name(f"  {decomposed}   Müller ") == "José Müller"


def test_duplicate_email_is_case_insensitive_and_points_to_the_first_row() -> None:
    result = screen_recipients(
        [
            RecipientInput(name="Ada Lovelace", email="ada@example.com"),
            RecipientInput(name="Ada Again", email="  ADA@Example.com "),
        ]
    )

    assert [row.position for row in result.valid] == [0]
    assert result.rejected[0].error_code == "EMAIL_DUPLICATE"
    assert "position 0" in result.rejected[0].error_message


def test_a_rejected_row_does_not_claim_its_email() -> None:
    result = screen_recipients(
        [
            RecipientInput(name="", email="ada@example.com"),
            RecipientInput(name="Ada Lovelace", email="ada@example.com"),
        ]
    )

    assert [row.position for row in result.valid] == [1]


def test_bad_rows_are_rejected_and_good_rows_are_still_issued(client: TestClient) -> None:
    payload = job_payload(
        [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "Bad Email", "email": "nope"},
            {"name": "Duplicate", "email": "ADA@example.com"},
            {"name": "Grace Hopper", "email": "grace@example.com"},
        ]
    )
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    items = client.get(f"{JOBS_URL}/{job_id}/certificates").json()["items"]
    outcome = {item["position"]: (item["status"], item["error_code"]) for item in items}

    assert outcome == {
        0: ("issued", None),
        1: ("rejected", "EMAIL_INVALID"),
        2: ("rejected", "EMAIL_DUPLICATE"),
        3: ("issued", None),
    }
    assert client.get(f"{JOBS_URL}/{job_id}").json()["status"] == "completed_with_errors"


def test_missing_recipient_fields_reject_the_row_not_the_request(client: TestClient) -> None:
    payload = job_payload([{"name": "Ada Lovelace", "email": "ada@example.com"}, {"phone": "1"}])

    response = client.post(JOBS_URL, json=payload)

    assert response.status_code == 202
    assert response.json()["rejected"][0]["error_code"] == "NAME_BLANK"


def test_strict_mode_rejects_the_whole_request_listing_every_bad_row(client: TestClient) -> None:
    payload = job_payload(
        [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "", "email": "blank@example.com"},
            {"name": "Grace Hopper", "email": "nope"},
        ]
    )

    response = client.post(f"{JOBS_URL}?strict=true", json=payload)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_RECIPIENTS"
    assert [(row["position"], row["error_code"]) for row in error["details"]] == [
        (1, "NAME_BLANK"),
        (2, "EMAIL_INVALID"),
    ]


def test_strict_mode_accepts_a_fully_valid_request(client: TestClient) -> None:
    payload = job_payload([{"name": "Ada Lovelace", "email": "ada@example.com"}])

    assert client.post(f"{JOBS_URL}?strict=true", json=payload).status_code == 202

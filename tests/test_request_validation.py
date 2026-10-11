"""Request-level validation: the whole request is refused with 422, in the envelope."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from certgen.models import CertificateJob
from tests.conftest import JOBS_URL, db_session, job_payload, recipients


def assert_error_envelope(response: Any, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


def assert_no_job_created(client: TestClient) -> None:
    with db_session(client) as session:
        assert session.scalar(select(func.count()).select_from(CertificateJob)) == 0


def test_empty_recipient_list_is_rejected(client: TestClient) -> None:
    response = client.post(JOBS_URL, json=job_payload([]))

    error = assert_error_envelope(response, 422, "VALIDATION_ERROR")
    assert error["details"][0]["location"] == "body.recipients"
    assert_no_job_created(client)


def test_too_many_recipients_is_rejected(client: TestClient) -> None:
    eleven = [{"name": f"Person {index}", "email": f"p{index}@example.com"} for index in range(11)]

    response = client.post(JOBS_URL, json=job_payload(eleven))

    error = assert_error_envelope(response, 422, "VALIDATION_ERROR")
    assert "at most 10" in error["message"]
    assert_no_job_created(client)


def test_missing_title_is_rejected(client: TestClient) -> None:
    payload = job_payload(recipients("Ada Lovelace"))
    del payload["certificate"]["title"]

    error = assert_error_envelope(client.post(JOBS_URL, json=payload), 422, "VALIDATION_ERROR")
    assert any(detail["location"] == "body.certificate.title" for detail in error["details"])


def test_blank_title_is_rejected(client: TestClient) -> None:
    payload = job_payload(recipients("Ada Lovelace"), title="   ")

    assert_error_envelope(client.post(JOBS_URL, json=payload), 422, "VALIDATION_ERROR")


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        JOBS_URL, content=b"{not json", headers={"Content-Type": "application/json"}
    )

    assert_error_envelope(response, 422, "VALIDATION_ERROR")


def test_unknown_certificate_kind_is_rejected(client: TestClient) -> None:
    payload = job_payload(recipients("Ada Lovelace"), certificate_kind="BRAVERY")

    assert_error_envelope(client.post(JOBS_URL, json=payload), 422, "VALIDATION_ERROR")


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    assert_error_envelope(client.get("/api/v1/nope"), 404, "NOT_FOUND")


def test_unknown_job_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get(f"{JOBS_URL}/00000000-0000-0000-0000-000000000000")

    assert_error_envelope(response, 404, "JOB_NOT_FOUND")


def test_malformed_job_id_is_a_validation_error(client: TestClient) -> None:
    assert_error_envelope(client.get(f"{JOBS_URL}/not-a-uuid"), 422, "VALIDATION_ERROR")

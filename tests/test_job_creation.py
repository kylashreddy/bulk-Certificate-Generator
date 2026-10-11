from fastapi.testclient import TestClient
from sqlalchemy import select

from certgen.domain.statuses import CertificateStatus
from certgen.models import Certificate, CertificateJob
from tests.conftest import JOBS_URL, db_session, job_payload, recipients


def test_create_job_returns_202_with_location_and_counts(client: TestClient) -> None:
    response = client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace", "Alan Turing")))

    assert response.status_code == 202
    body = response.json()
    assert body["accepted_count"] == 2
    assert body["rejected_count"] == 0
    assert body["rejected"] == []
    assert response.headers["Location"] == f"/api/v1/jobs/{body['job_id']}"
    assert body["status_url"] == response.headers["Location"]


def test_create_job_persists_job_and_one_row_per_recipient(client: TestClient) -> None:
    payload = job_payload(recipients("Ada Lovelace", "Alan Turing", "Grace Hopper"))
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    with db_session(client) as session:
        job = session.scalars(select(CertificateJob)).one()
        rows = session.scalars(select(Certificate).order_by(Certificate.position)).all()

    assert str(job.id) == job_id
    assert job.title == "Advanced Data Engineering"
    assert [row.position for row in rows] == [0, 1, 2]
    assert [row.recipient_name for row in rows] == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert all(row.serial and row.serial.startswith("BCG-2026-") for row in rows)
    assert len({row.verification_code for row in rows}) == 3


def test_serial_numbers_follow_the_documented_format(client: TestClient) -> None:
    client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace", "Alan Turing")))

    with db_session(client) as session:
        job = session.scalars(select(CertificateJob)).one()
        serials = session.scalars(select(Certificate.serial).order_by(Certificate.position)).all()

    assert serials == [f"BCG-2026-{job.serial_prefix}-00001", f"BCG-2026-{job.serial_prefix}-00002"]


def test_mixed_batch_reports_rejected_rows_in_the_202_response(client: TestClient) -> None:
    payload = job_payload(
        [
            {"name": "Ada Lovelace", "email": "ada@example.com"},
            {"name": "", "email": "nobody@example.com"},
            {"name": "Grace Hopper", "email": "not-an-email"},
        ]
    )
    body = client.post(JOBS_URL, json=payload).json()

    assert body["accepted_count"] == 1
    assert body["rejected_count"] == 2
    assert [(row["position"], row["error_code"]) for row in body["rejected"]] == [
        (1, "NAME_BLANK"),
        (2, "EMAIL_INVALID"),
    ]

    with db_session(client) as session:
        statuses = session.scalars(select(Certificate.status).order_by(Certificate.position)).all()
    assert statuses == [
        CertificateStatus.ISSUED,
        CertificateStatus.REJECTED,
        CertificateStatus.REJECTED,
    ]


def test_defaults_are_applied_for_optional_certificate_fields(client: TestClient) -> None:
    payload = job_payload(recipients("Ada Lovelace"))
    del payload["certificate"]["certificate_kind"]
    del payload["certificate"]["achievement_line"]

    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]
    details = client.get(f"{JOBS_URL}/{job_id}").json()["certificate"]

    assert details["certificate_kind"] == "COMPLETION"
    assert details["achievement_line"] == ""

"""Idempotency-Key handling and crash recovery at startup."""

from sqlalchemy import func, select, update

from certgen.config import Settings
from certgen.db.migrations import upgrade_to_head
from certgen.db.session import build_engine, build_session_factory
from certgen.domain.statuses import CertificateStatus, JobStatus
from certgen.models import Certificate, CertificateJob
from certgen.schemas.job_requests import CreateJobRequest
from certgen.services.job_creation import create_job
from tests.conftest import (
    JOBS_URL,
    ClientFactory,
    FakeRenderer,
    db_session,
    job_payload,
    recipients,
)


def test_same_idempotency_key_returns_the_original_job(make_client: ClientFactory) -> None:
    client = make_client()
    payload = job_payload(recipients("Ada Lovelace", "Alan Turing"))
    headers = {"Idempotency-Key": "order-1234"}

    first = client.post(JOBS_URL, json=payload, headers=headers)
    second = client.post(JOBS_URL, json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["accepted_count"] == 2
    with db_session(client) as session:
        assert session.scalar(select(func.count()).select_from(CertificateJob)) == 1
        assert session.scalar(select(func.count()).select_from(Certificate)) == 2


def test_replay_does_not_render_again(make_client: ClientFactory) -> None:
    renderer = FakeRenderer()
    client = make_client(renderer=renderer)
    payload = job_payload(recipients("Ada Lovelace"))
    for _ in range(3):
        client.post(JOBS_URL, json=payload, headers={"Idempotency-Key": "k"})

    assert len(renderer.rendered) == 1


def test_same_key_with_a_different_body_is_a_conflict(make_client: ClientFactory) -> None:
    client = make_client()
    headers = {"Idempotency-Key": "order-1234"}
    client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace")), headers=headers)

    response = client.post(JOBS_URL, json=job_payload(recipients("Mallory")), headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_requests_without_a_key_always_create_new_jobs(make_client: ClientFactory) -> None:
    client = make_client()
    payload = job_payload(recipients("Ada Lovelace"))

    first = client.post(JOBS_URL, json=payload).json()["job_id"]
    second = client.post(JOBS_URL, json=payload).json()["job_id"]

    assert first != second


def test_startup_recovery_finishes_rows_left_rendering_by_a_crash(
    settings: Settings, make_client: ClientFactory
) -> None:
    # Simulate a process that crashed mid-job: job "running", one row stuck in
    # "rendering", one still "pending", and no worker alive.
    upgrade_to_head(settings.database_url)
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        request = CreateJobRequest.model_validate(
            job_payload(recipients("Ada Lovelace", "Alan Turing"))
        )
        job = create_job(
            session, request, idempotency_key=None, strict=False, max_recipients=10
        ).job
        session.execute(
            update(CertificateJob)
            .where(CertificateJob.id == job.id)
            .values(status=JobStatus.RUNNING)
        )
        session.execute(
            update(Certificate)
            .where(Certificate.job_id == job.id, Certificate.position == 0)
            .values(status=CertificateStatus.RENDERING)
        )
        session.commit()
    engine.dispose()

    # Starting the app runs recovery in the lifespan; InlineDispatcher finishes the job.
    client = make_client()

    body = client.get(f"{JOBS_URL}/{job.id}").json()
    assert body["status"] == "completed"
    assert body["progress"]["issued"] == 2
    assert body["progress"]["rendering"] == 0


def test_startup_recovery_ignores_finished_jobs(make_client: ClientFactory) -> None:
    client = make_client()
    client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace")))

    # A second app on the same database behaves like a restart: recovery runs again.
    restarted_renderer = FakeRenderer()
    make_client(renderer=restarted_renderer)

    assert restarted_renderer.rendered == []

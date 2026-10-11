"""Status machines, progress, failure isolation, retries, and the thread-pool path."""

import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from certgen.config import DispatcherKind, Settings
from certgen.domain.statuses import (
    CertificateStatus,
    InvalidTransition,
    JobStatus,
    transition_certificate,
    transition_job,
)
from certgen.models import Certificate
from certgen.services.job_progress import JobProgress, final_job_status
from tests.conftest import (
    JOBS_URL,
    ClientFactory,
    FailingForRecipientRenderer,
    FlakyStorage,
    SleepRecorder,
    db_session,
    job_payload,
    recipients,
)


class _Job:
    def __init__(self, status: JobStatus) -> None:
        self.status = status


class _Certificate:
    def __init__(self, status: CertificateStatus) -> None:
        self.status = status


# --- state machines ----------------------------------------------------------------


def test_job_follows_the_happy_path() -> None:
    job = _Job(JobStatus.QUEUED)
    transition_job(job, JobStatus.RUNNING)
    transition_job(job, JobStatus.COMPLETED)
    assert job.status == JobStatus.COMPLETED


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (JobStatus.QUEUED, JobStatus.COMPLETED),
        (JobStatus.COMPLETED, JobStatus.RUNNING),
        (JobStatus.RUNNING, JobStatus.QUEUED),
    ],
)
def test_illegal_job_transitions_raise(current: JobStatus, requested: JobStatus) -> None:
    with pytest.raises(InvalidTransition):
        transition_job(_Job(current), requested)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (CertificateStatus.REJECTED, CertificateStatus.PENDING),
        (CertificateStatus.PENDING, CertificateStatus.ISSUED),
        (CertificateStatus.ISSUED, CertificateStatus.RENDERING),
    ],
)
def test_illegal_certificate_transitions_raise(
    current: CertificateStatus, requested: CertificateStatus
) -> None:
    certificate = _Certificate(current)
    with pytest.raises(InvalidTransition):
        transition_certificate(certificate, requested)
    assert certificate.status == current  # unchanged on failure


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (JobProgress(pending=0, rendering=0, issued=3, failed=0, rejected=0), JobStatus.COMPLETED),
        (
            JobProgress(pending=0, rendering=0, issued=2, failed=1, rejected=0),
            JobStatus.COMPLETED_WITH_ERRORS,
        ),
        (
            JobProgress(pending=0, rendering=0, issued=2, failed=0, rejected=1),
            JobStatus.COMPLETED_WITH_ERRORS,
        ),
        (JobProgress(pending=0, rendering=0, issued=0, failed=2, rejected=1), JobStatus.FAILED),
        (JobProgress(pending=0, rendering=0, issued=0, failed=0, rejected=2), JobStatus.FAILED),
    ],
)
def test_final_status_is_computed_from_counts(progress: JobProgress, expected: JobStatus) -> None:
    assert final_job_status(progress) == expected


def test_percent_complete_counts_every_terminal_row() -> None:
    progress = JobProgress(pending=1, rendering=1, issued=4, failed=1, rejected=1)
    assert progress.total == 8
    assert progress.percent_complete == 75.0


# --- job status endpoint -------------------------------------------------------------


def test_completed_job_reports_full_progress_and_timestamps(client: TestClient) -> None:
    job_id = client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace", "Alan Turing")))
    body = client.get(f"{JOBS_URL}/{job_id.json()['job_id']}").json()

    assert body["status"] == "completed"
    assert body["progress"] == {
        "total": 2,
        "pending": 0,
        "rendering": 0,
        "issued": 2,
        "failed": 0,
        "rejected": 0,
        "percent_complete": 100.0,
    }
    assert body["created_at"] <= body["started_at"] <= body["finished_at"]


def test_job_with_only_rejected_rows_finishes_as_failed(client: TestClient) -> None:
    payload = job_payload([{"name": "", "email": "x@example.com"}])
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    body = client.get(f"{JOBS_URL}/{job_id}").json()
    assert body["status"] == "failed"
    assert body["progress"]["rejected"] == 1


# --- failure isolation -----------------------------------------------------------------


def test_one_failing_certificate_does_not_stop_the_others(make_client: ClientFactory) -> None:
    client = make_client(renderer=FailingForRecipientRenderer("Alan Turing"))
    payload = job_payload(recipients("Ada Lovelace", "Alan Turing", "Grace Hopper"))
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    job = client.get(f"{JOBS_URL}/{job_id}").json()
    items = client.get(f"{JOBS_URL}/{job_id}/certificates").json()["items"]

    assert job["status"] == "completed_with_errors"
    assert job["progress"]["issued"] == 2
    assert job["progress"]["failed"] == 1
    failed = [item for item in items if item["status"] == "failed"]
    assert [item["recipient_name"] for item in failed] == ["Alan Turing"]
    assert failed[0]["error_code"] == "RENDER_ERROR"
    assert "cannot typeset Alan Turing" in failed[0]["error_message"]
    assert failed[0]["download_url"] is None


def test_deterministic_errors_are_not_retried(make_client: ClientFactory) -> None:
    client = make_client(renderer=FailingForRecipientRenderer("Alan Turing"))
    client.post(JOBS_URL, json=job_payload(recipients("Alan Turing")))

    with db_session(client) as session:
        certificate = session.scalars(select(Certificate)).one()
    assert certificate.attempts == 1


def test_transient_storage_error_is_retried_with_backoff_then_succeeds(
    make_client: ClientFactory, tmp_path: Path, sleep_recorder: SleepRecorder
) -> None:
    storage = FlakyStorage(tmp_path / "flaky", failures=2)
    client = make_client(storage=storage)
    job_id = client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace"))).json()["job_id"]

    with db_session(client) as session:
        certificate = session.scalars(select(Certificate)).one()
    assert certificate.status == CertificateStatus.ISSUED
    assert certificate.attempts == 3
    assert storage.save_calls == 3
    assert sleep_recorder.delays == [0.5, 1.0]  # exponential backoff
    assert client.get(f"{JOBS_URL}/{job_id}").json()["status"] == "completed"


def test_transient_error_fails_the_row_once_attempts_are_exhausted(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    client = make_client(storage=FlakyStorage(tmp_path / "flaky", failures=99))
    payload = job_payload(recipients("Ada Lovelace"))
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]

    item = client.get(f"{JOBS_URL}/{job_id}/certificates").json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "TRANSIENT_ERROR"
    assert client.get(f"{JOBS_URL}/{job_id}").json()["status"] == "failed"


# --- retry endpoint -----------------------------------------------------------------------


def test_retry_requeues_failed_rows_but_not_rejected_ones(make_client: ClientFactory) -> None:
    renderer = FailingForRecipientRenderer("Alan Turing")
    client = make_client(renderer=renderer)
    payload = job_payload(
        [*recipients("Ada Lovelace", "Alan Turing"), {"name": "", "email": "x@example.com"}]
    )
    job_id = client.post(JOBS_URL, json=payload).json()["job_id"]
    renderer.failing_name = "nobody"  # the underlying problem is "fixed"

    response = client.post(f"{JOBS_URL}/{job_id}/retry")

    assert response.status_code == 202
    assert response.json()["requeued_count"] == 1
    job = client.get(f"{JOBS_URL}/{job_id}").json()
    assert job["progress"]["issued"] == 2
    assert job["progress"]["rejected"] == 1
    assert job["status"] == "completed_with_errors"


def test_retry_refuses_a_job_without_failures(client: TestClient) -> None:
    job_id = client.post(JOBS_URL, json=job_payload(recipients("Ada Lovelace"))).json()["job_id"]

    response = client.post(f"{JOBS_URL}/{job_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_NOT_RETRYABLE"


# --- background thread pool ------------------------------------------------------------------


def test_thread_pool_dispatcher_processes_jobs_in_the_background(
    make_client: ClientFactory, settings: Settings
) -> None:
    threaded = settings.model_copy(
        update={
            "dispatcher": DispatcherKind.THREAD,
            "worker_pool_size": 2,
            "processing_chunk_size": 2,
        }
    )
    client = make_client(app_settings=threaded)
    names = [f"Person {index}" for index in range(7)]
    job_id = client.post(JOBS_URL, json=job_payload(recipients(*names))).json()["job_id"]

    body = _wait_for_final_status(client, uuid.UUID(job_id))

    assert body["status"] == "completed"
    assert body["progress"]["issued"] == 7


def _wait_for_final_status(client: TestClient, job_id: uuid.UUID) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body: dict[str, object] = client.get(f"{JOBS_URL}/{job_id}").json()
        if body["status"] not in ("queued", "running"):
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish within 10 seconds")

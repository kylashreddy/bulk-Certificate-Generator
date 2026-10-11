"""Shared fixtures: a temp SQLite database per test, InlineDispatcher (so a job is
finished by the time POST returns), temp storage, and swappable renderers."""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from certgen.composition import AppServices, build_app_services
from certgen.config import DispatcherKind, Settings
from certgen.main import create_app
from certgen.rendering.protocol import CertificateRenderer, RenderContext
from certgen.storage.local_disk import LocalDiskStorage
from certgen.storage.protocol import CertificateStorage

JOBS_URL = "/api/v1/jobs"


class FakeRenderer:
    """Fast stand-in for ReportLab: a tiny PDF-looking payload containing the name."""

    def __init__(self) -> None:
        self.rendered: list[RenderContext] = []

    def render(self, context: RenderContext) -> bytes:
        self.rendered.append(context)
        return f"%PDF-1.4 fake certificate for {context.recipient_name}".encode()


class FailingForRecipientRenderer(FakeRenderer):
    """Raises a deterministic error for one specific recipient, renders everyone else."""

    def __init__(self, failing_name: str) -> None:
        super().__init__()
        self.failing_name = failing_name

    def render(self, context: RenderContext) -> bytes:
        if context.recipient_name == self.failing_name:
            raise ValueError(f"cannot typeset {context.recipient_name}")
        return super().render(context)


class FlakyStorage:
    """Raises OSError for the first `failures` saves, then behaves like disk storage."""

    def __init__(self, root: Path, failures: int) -> None:
        self._delegate = LocalDiskStorage(root)
        self.remaining_failures = failures
        self.save_calls = 0

    def save(self, job_id: uuid.UUID, serial: str, pdf_bytes: bytes) -> str:
        self.save_calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise OSError("storage temporarily unavailable")
        return self._delegate.save(job_id, serial, pdf_bytes)

    def read(self, file_key: str) -> bytes:
        return self._delegate.read(file_key)


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "storage",
        dispatcher=DispatcherKind.INLINE,
        max_recipients_per_job=10,
        max_render_attempts=3,
        retry_backoff_seconds=0.5,
        public_base_url="http://testserver",
        log_level="WARNING",
    )


@pytest.fixture
def sleep_recorder() -> SleepRecorder:
    return SleepRecorder()


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(settings: Settings, sleep_recorder: SleepRecorder) -> Iterator[ClientFactory]:
    """Build a TestClient with chosen renderer/storage. Entering the client runs the
    app lifespan: migrations, dispatcher start, startup recovery."""
    clients: list[TestClient] = []

    def factory(
        renderer: CertificateRenderer | None = None,
        storage: CertificateStorage | None = None,
        app_settings: Settings | None = None,
    ) -> TestClient:
        chosen_renderer = renderer or FakeRenderer()

        def services_factory(active: Settings) -> AppServices:
            return build_app_services(
                active, renderer=chosen_renderer, storage=storage, sleep=sleep_recorder
            )

        client = TestClient(create_app(app_settings or settings, services_factory))
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: ClientFactory) -> TestClient:
    return make_client()


def db_session(client: TestClient) -> Session:
    services: AppServices = client.app.state.services  # type: ignore[attr-defined]
    return services.session_factory()


def certificate_payload(**overrides: Any) -> dict[str, Any]:
    details = {
        "title": "Advanced Data Engineering",
        "achievement_line": "for successfully completing the professional programme",
        "certificate_kind": "COMPLETION",
        "issued_on": "2026-10-11",
        "issuer_name": "Northwind Academy",
        "signatory_name": "Dr. Amara Okafor",
        "signatory_title": "Director of Programmes",
    }
    details.update(overrides)
    return details


def job_payload(recipients: list[dict[str, Any]], **certificate_overrides: Any) -> dict[str, Any]:
    return {"certificate": certificate_payload(**certificate_overrides), "recipients": recipients}


def recipients(*names: str) -> list[dict[str, str]]:
    return [
        {"name": name, "email": f"{name.lower().replace(' ', '.')}@example.com"} for name in names
    ]

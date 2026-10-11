"""FastAPI dependencies. They only hand out objects built in composition.py."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from certgen.composition import AppServices
from certgen.config import Settings
from certgen.dispatch.dispatchers import Dispatcher
from certgen.storage.protocol import CertificateStorage


def get_app_services(request: Request) -> AppServices:
    services: AppServices = request.app.state.services
    return services


def get_session(request: Request) -> Iterator[Session]:
    session = get_app_services(request).session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings_dependency(request: Request) -> Settings:
    return get_app_services(request).settings


def get_dispatcher(request: Request) -> Dispatcher:
    return get_app_services(request).dispatcher


def get_storage(request: Request) -> CertificateStorage:
    return get_app_services(request).storage

"""FastAPI application factory and lifespan."""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from certgen.api.error_handlers import register_error_handlers
from certgen.api.presenters import API_PREFIX
from certgen.api.routes import certificates, health, jobs
from certgen.composition import AppServices, build_app_services
from certgen.config import Settings, get_settings
from certgen.db.migrations import upgrade_to_head
from certgen.logging_setup import configure_logging
from certgen.services.startup_recovery import recover_interrupted_work

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    services_factory: Callable[[Settings], AppServices] = build_app_services,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.run_migrations_on_startup:
            upgrade_to_head(settings.database_url)
        services = services_factory(settings)
        app.state.services = services
        services.dispatcher.start()
        _resume_unfinished_jobs(services)
        try:
            yield
        finally:
            services.dispatcher.shutdown()
            services.engine.dispose()

    app = FastAPI(
        title="Bulk Certificate Generator",
        version="1.0.0",
        description="Submit many recipients in one request; get one PDF certificate each.",
        lifespan=lifespan,
    )
    register_error_handlers(app)
    app.include_router(jobs.router, prefix=API_PREFIX)
    app.include_router(certificates.router, prefix=API_PREFIX)
    app.include_router(health.router)
    return app


def _resume_unfinished_jobs(services: AppServices) -> None:
    with services.session_factory() as session:
        job_ids = recover_interrupted_work(session)
    for job_id in job_ids:
        services.dispatcher.submit(job_id)

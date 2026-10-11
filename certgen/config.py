"""Application settings, read from environment variables or a .env file."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class DispatcherKind(StrEnum):
    THREAD = "thread"
    INLINE = "inline"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./certgen.db"
    storage_dir: Path = Path("./storage")
    # Zero-setup local runs: apply Alembic migrations when the app starts. Turn off
    # when several replicas start at once and migrations run as a separate deploy step.
    run_migrations_on_startup: bool = True

    dispatcher: DispatcherKind = DispatcherKind.THREAD
    worker_pool_size: int = 4
    processing_chunk_size: int = 50

    max_recipients_per_job: int = 5000
    max_render_attempts: int = 3
    retry_backoff_seconds: float = 0.5

    # Printed into the QR code, so it must be the externally reachable address.
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

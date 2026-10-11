"""CertificateJob: one bulk request and the certificate details shared by all its rows."""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from certgen.db.base import Base, UtcDateTime, utc_now
from certgen.domain.statuses import JobStatus

if TYPE_CHECKING:
    from certgen.models.certificate import Certificate


class CertificateKind(StrEnum):
    COMPLETION = "COMPLETION"
    PARTICIPATION = "PARTICIPATION"
    ACHIEVEMENT = "ACHIEVEMENT"


def string_enum(enum_class: type[StrEnum], name: str) -> Enum:
    """Store enums as VARCHAR + CHECK so SQLite and PostgreSQL behave identically,
    and adding a value never needs a PostgreSQL ALTER TYPE."""
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [member.value for member in members],
    )


class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[JobStatus] = mapped_column(
        string_enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )

    title: Mapped[str] = mapped_column(String(200))
    achievement_line: Mapped[str] = mapped_column(String(300))
    certificate_kind: Mapped[CertificateKind] = mapped_column(
        string_enum(CertificateKind, "certificate_kind")
    )
    issued_on: Mapped[date] = mapped_column(Date)
    issuer_name: Mapped[str] = mapped_column(String(120))
    signatory_name: Mapped[str] = mapped_column(String(120))
    signatory_title: Mapped[str] = mapped_column(String(120))

    serial_prefix: Mapped[str] = mapped_column(String(4), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    certificates: Mapped[list["Certificate"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="Certificate.position",
        lazy="raise",  # forces services to load rows explicitly, never by accident
    )

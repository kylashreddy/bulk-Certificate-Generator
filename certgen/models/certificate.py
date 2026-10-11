"""Certificate: one row per recipient, including recipients that failed validation."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from certgen.db.base import Base, UtcDateTime, utc_now
from certgen.domain.statuses import CertificateStatus
from certgen.models.job import CertificateJob, string_enum


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_certificates_job_id_position"),
        Index("ix_certificates_job_id_status", "job_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("certificate_jobs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)

    # Text, not VARCHAR(120): rejected rows keep the raw input, which may be too long.
    recipient_name: Mapped[str] = mapped_column(Text)
    recipient_email: Mapped[str] = mapped_column(Text)

    status: Mapped[CertificateStatus] = mapped_column(
        string_enum(CertificateStatus, "certificate_status")
    )
    serial: Mapped[str | None] = mapped_column(String(32), unique=True)
    verification_code: Mapped[str | None] = mapped_column(String(32), unique=True)
    file_key: Mapped[str | None] = mapped_column(String(255))

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utc_now, onupdate=utc_now)
    issued_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    job: Mapped[CertificateJob] = relationship(back_populates="certificates", lazy="raise")

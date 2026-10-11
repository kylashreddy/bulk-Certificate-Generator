"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-11

Enums are VARCHAR + CHECK (native_enum=False), so this migration is identical on
SQLite and PostgreSQL. The values are spelled out here rather than imported from
the models: a migration must describe the schema as it was, not as it is now.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.create_table(
        "certificate_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            _string_enum(
                "job_status", "queued", "running", "completed", "completed_with_errors", "failed"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("achievement_line", sa.String(length=300), nullable=False),
        sa.Column(
            "certificate_kind",
            _string_enum("certificate_kind", "COMPLETION", "PARTICIPATION", "ACHIEVEMENT"),
            nullable=False,
        ),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("issuer_name", sa.String(length=120), nullable=False),
        sa.Column("signatory_name", sa.String(length=120), nullable=False),
        sa.Column("signatory_title", sa.String(length=120), nullable=False),
        sa.Column("serial_prefix", sa.String(length=4), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_certificate_jobs_idempotency_key"),
        sa.UniqueConstraint("serial_prefix", name="uq_certificate_jobs_serial_prefix"),
    )
    op.create_table(
        "certificates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("recipient_email", sa.Text(), nullable=False),
        sa.Column(
            "status",
            _string_enum(
                "certificate_status", "rejected", "pending", "rendering", "issued", "failed"
            ),
            nullable=False,
        ),
        sa.Column("serial", sa.String(length=32), nullable=True),
        sa.Column("verification_code", sa.String(length=32), nullable=True),
        sa.Column("file_key", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["certificate_jobs.id"],
            name="fk_certificates_job_id_certificate_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_certificates"),
        sa.UniqueConstraint("job_id", "position", name="uq_certificates_job_id_position"),
        sa.UniqueConstraint("serial", name="uq_certificates_serial"),
        sa.UniqueConstraint("verification_code", name="uq_certificates_verification_code"),
    )
    op.create_index("ix_certificates_job_id_status", "certificates", ["job_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_certificates_job_id_status", table_name="certificates")
    op.drop_table("certificates")
    op.drop_table("certificate_jobs")

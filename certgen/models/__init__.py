"""Importing this package registers every model on Base.metadata (needed by Alembic)."""

from certgen.models.certificate import Certificate
from certgen.models.job import CertificateJob, CertificateKind

__all__ = ["Certificate", "CertificateJob", "CertificateKind"]

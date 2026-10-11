"""Streamed ZIP of a job's issued PDFs plus a manifest.csv covering every row.

Two steps on purpose:
1. `snapshot_job_archive` reads the rows into plain dataclasses while the request's
   database session is open.
2. `stream_job_archive` yields ZIP bytes with no database access at all, because
   the response body is sent after the request's session has closed.

Memory stays flat: at most one PDF is held at a time, and each finished entry is
flushed to the client immediately.
"""

import csv
import io
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from certgen.domain.statuses import CertificateStatus
from certgen.models import Certificate
from certgen.services.certificate_queries import get_job
from certgen.storage.protocol import CertificateStorage

MANIFEST_COLUMNS = (
    "position",
    "recipient_name",
    "recipient_email",
    "status",
    "serial",
    "error_code",
    "error_message",
)


@dataclass(frozen=True)
class ArchiveRow:
    position: int
    recipient_name: str
    recipient_email: str
    status: str
    serial: str | None
    error_code: str | None
    error_message: str | None
    file_key: str | None


@dataclass(frozen=True)
class JobArchiveSnapshot:
    job_id: uuid.UUID
    rows: list[ArchiveRow]


def snapshot_job_archive(session: Session, job_id: uuid.UUID) -> JobArchiveSnapshot:
    get_job(session, job_id)
    certificates = session.scalars(
        select(Certificate).where(Certificate.job_id == job_id).order_by(Certificate.position)
    )
    rows = [
        ArchiveRow(
            position=certificate.position,
            recipient_name=certificate.recipient_name,
            recipient_email=certificate.recipient_email,
            status=certificate.status.value,
            serial=certificate.serial,
            error_code=certificate.error_code,
            error_message=certificate.error_message,
            file_key=certificate.file_key
            if certificate.status == CertificateStatus.ISSUED
            else None,
        )
        for certificate in certificates
    ]
    return JobArchiveSnapshot(job_id, rows)


class _ChunkSink(io.RawIOBase):
    """A write-only, non-seekable file object that collects bytes until drained.

    ZipFile detects that it cannot seek and writes data descriptors after each
    entry instead of patching headers, which is what makes true streaming possible.
    """

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, chunk: bytes) -> int:  # type: ignore[override]
        self._chunks.append(bytes(chunk))
        return len(chunk)

    def drain(self) -> bytes:
        drained = b"".join(self._chunks)
        self._chunks.clear()
        return drained


def stream_job_archive(
    snapshot: JobArchiveSnapshot, storage: CertificateStorage
) -> Iterator[bytes]:
    sink = _ChunkSink()
    with ZipFile(sink, mode="w") as archive:
        for row in snapshot.rows:
            if row.file_key is None or row.serial is None:
                continue
            # PDFs are already compressed internally; deflating them again wastes CPU.
            archive.writestr(f"{row.serial}.pdf", storage.read(row.file_key), ZIP_STORED)
            yield sink.drain()
        archive.writestr("manifest.csv", build_manifest_csv(snapshot.rows), ZIP_DEFLATED)
    yield sink.drain()


def build_manifest_csv(rows: list[ArchiveRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(MANIFEST_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.position,
                spreadsheet_safe(row.recipient_name),
                spreadsheet_safe(row.recipient_email),
                row.status,
                row.serial or "",
                row.error_code or "",
                row.error_message or "",
            ]
        )
    return buffer.getvalue()


def spreadsheet_safe(cell: str) -> str:
    """Recipient names are user input and the manifest is likely opened in Excel; a
    leading = + - @ would be executed as a formula (CSV injection). A leading quote
    makes the spreadsheet treat it as text."""
    return f"'{cell}" if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell

"""Where finished PDFs live. Services depend on this protocol, never on the disk."""

import uuid
from typing import Protocol


class CertificateStorage(Protocol):
    def save(self, job_id: uuid.UUID, serial: str, pdf_bytes: bytes) -> str:
        """Persist the PDF and return an opaque file key to store on the row."""
        ...

    def read(self, file_key: str) -> bytes: ...

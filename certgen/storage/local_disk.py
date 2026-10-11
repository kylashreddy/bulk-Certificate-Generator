"""Files on local disk at {root}/{job_id}/{serial}.pdf."""

import os
import tempfile
import uuid
from pathlib import Path


class LocalDiskStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def save(self, job_id: uuid.UUID, serial: str, pdf_bytes: bytes) -> str:
        file_key = f"{job_id}/{serial}.pdf"
        destination = self._resolve(file_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename: os.replace is atomic, so a crash never
        # leaves a half-written PDF under the final name.
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            handle.write(pdf_bytes)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, destination)
        return file_key

    def read(self, file_key: str) -> bytes:
        return self._resolve(file_key).read_bytes()

    def _resolve(self, file_key: str) -> Path:
        path = (self._root / file_key).resolve()
        # File keys come from our own database, but refusing anything outside the
        # root means a corrupted key can never read arbitrary files.
        if not path.is_relative_to(self._root):
            raise ValueError(f"File key escapes storage root: {file_key!r}")
        return path

"""Safe download filenames built from recipient names (which are user input)."""

import re
import unicodedata
from urllib.parse import quote

_UNSAFE_FILENAME_CHARACTERS = re.compile(r"[^A-Za-z0-9_-]+")
_UNSAFE_UNICODE_CHARACTERS = re.compile(r"[\\/:*?\"<>|\x00-\x1f\x7f;]+|\s+")


def attachment_header(recipient_name: str, serial: str) -> str:
    """Two filenames, per RFC 6266: an ASCII-only `filename` every client understands
    and a UTF-8 `filename*` that modern browsers prefer, so "José" stays "José".
    Quotes, slashes, semicolons and newlines are removed, which rules out header
    injection and path tricks like "../../etc/passwd"."""
    ascii_name = _ascii_filename_stem(recipient_name) or "certificate"
    unicode_name = (
        _UNSAFE_UNICODE_CHARACTERS.sub("_", recipient_name).strip("_.")[:80] or "certificate"
    )
    ascii_filename = f"{ascii_name}_{serial}.pdf"
    unicode_filename = f"{unicode_name}_{serial}.pdf"
    return (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(unicode_filename, safe='')}"
    )


def _ascii_filename_stem(name: str) -> str:
    # NFKD splits "é" into "e" + combining accent; dropping non-ASCII keeps the "e".
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode()
    return _UNSAFE_FILENAME_CHARACTERS.sub("_", ascii_only).strip("_")[:80]

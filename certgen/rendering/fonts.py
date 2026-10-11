"""Bundled font registration and glyph-coverage fallback.

ReportLab cannot use variable fonts, so static TTF instances are bundled with their
OFL licences. Registration is process-wide and happens once, under a lock, because
worker threads may render their first certificate at the same moment.
"""

import threading
from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"


@dataclass(frozen=True)
class FontRole:
    name: str  # ReportLab registration name
    file_name: str
    fallback: str | None = None  # role name used when a glyph is missing


NAME_FALLBACK = FontRole("CertgenFallbackSerif", "NotoSerif-SemiBold.ttf")
ITALIC_FALLBACK = FontRole("CertgenFallbackSerifItalic", "NotoSerif-Italic.ttf")
NAME = FontRole("CertgenName", "CormorantGaramond-SemiBold.ttf", NAME_FALLBACK.name)
ITALIC = FontRole("CertgenItalic", "CormorantGaramond-Italic.ttf", ITALIC_FALLBACK.name)
LABEL = FontRole("CertgenLabel", "IBMPlexSansCondensed-Medium.ttf", NAME_FALLBACK.name)
MONO = FontRole("CertgenMono", "IBMPlexMono-Regular.ttf", NAME_FALLBACK.name)

ALL_ROLES = (NAME_FALLBACK, ITALIC_FALLBACK, NAME, ITALIC, LABEL, MONO)
_FALLBACK_BY_NAME = {role.name: role.fallback for role in ALL_ROLES}

_registration_lock = threading.Lock()
_registered = False


def register_fonts() -> None:
    global _registered
    with _registration_lock:
        if _registered:
            return
        for role in ALL_ROLES:
            pdfmetrics.registerFont(TTFont(role.name, str(FONT_DIR / role.file_name)))
        _registered = True


def font_covers(font_name: str, text: str) -> bool:
    font = pdfmetrics.getFont(font_name)
    glyph_map: dict[int, int] = font.face.charToGlyph
    return all(ord(character) in glyph_map for character in text if not character.isspace())


def font_for_text(font_name: str, text: str) -> str:
    """Use the designed face when it has every glyph; otherwise switch the whole
    string to the Noto Serif fallback (mixing faces mid-word looks broken).
    Scripts Noto Serif lacks too (e.g. CJK) still render as missing-glyph boxes:
    a documented limitation."""
    fallback = _FALLBACK_BY_NAME.get(font_name)
    if fallback is None or font_covers(font_name, text):
        return font_name
    return fallback

"""The real ReportLab renderer: valid PDFs, the right text, layout that never overflows."""

import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from pypdf import PdfReader

from certgen.rendering import fonts
from certgen.rendering.design_tokens import LAYOUT, TYPE
from certgen.rendering.protocol import RenderContext
from certgen.rendering.security_print import SecurityPrintRenderer, _fit_name
from certgen.rendering.text_fitting import text_width


def render_context(**overrides: object) -> RenderContext:
    values: dict[str, object] = {
        "recipient_name": "Ada Lovelace",
        "title": "Advanced Data Engineering",
        "achievement_line": "for successfully completing the professional programme",
        "certificate_kind": "COMPLETION",
        "issued_on": date(2026, 10, 11),
        "issuer_name": "Northwind Academy",
        "signatory_name": "Dr. Amara Okafor",
        "signatory_title": "Director of Programmes",
        "serial": "BCG-2026-K7Q4-00042",
        "verification_url": "http://testserver/api/v1/verify/abc123",
    }
    values.update(overrides)
    return RenderContext(**values)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def renderer() -> SecurityPrintRenderer:
    return SecurityPrintRenderer()


def extracted_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    return reader.pages[0].extract_text()


def test_output_is_a_pdf(renderer: SecurityPrintRenderer) -> None:
    pdf_bytes = renderer.render(render_context())
    assert pdf_bytes.startswith(b"%PDF")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")


def test_pdf_contains_name_title_and_serial(renderer: SecurityPrintRenderer) -> None:
    text = extracted_text(renderer.render(render_context()))

    assert "Ada Lovelace" in text
    assert "Advanced Data Engineering" in text
    assert "BCG-2026-K7Q4-00042" in text
    assert "CERTIFICATE OF COMPLETION" in text.replace("\n", " ")


def test_accented_name_is_rendered_with_its_accents(renderer: SecurityPrintRenderer) -> None:
    name = "Zoë Ångström-Núñez Łukasiewicz"
    text = extracted_text(renderer.render(render_context(recipient_name=name)))
    assert name in text


def test_pdf_is_a4_landscape(renderer: SecurityPrintRenderer) -> None:
    page = PdfReader(io.BytesIO(renderer.render(render_context()))).pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    assert (round(width), round(height)) == (842, 595)


@pytest.mark.parametrize(
    "name",
    [
        "Ada Lovelace",
        "Maximilian Alexander Konstantin von Hohenzollern-Sigmaringen-Wittelsbach",
        "A" * 120,  # one unbreakable word at the maximum allowed length
        " ".join(["Wolfeschlegelsteinhausenbergerdorff"] * 3),
    ],
)
def test_names_never_overflow_the_text_column(name: str) -> None:
    fonts.register_fonts()
    available = LAYOUT.text_right - LAYOUT.text_left
    fitted = _fit_name(name, fonts.NAME.name, available)

    assert fitted.font_size >= TYPE.hard_minimum_size
    for line in fitted.lines:
        assert text_width(line, fonts.NAME.name, fitted.font_size) <= available + 0.01


def test_short_names_use_one_line_at_full_size() -> None:
    fonts.register_fonts()
    fitted = _fit_name("Ada Lovelace", fonts.NAME.name, LAYOUT.text_right - LAYOUT.text_left)
    assert fitted.lines == ["Ada Lovelace"]
    assert fitted.font_size == TYPE.name_max_size


def test_long_names_wrap_to_two_lines() -> None:
    fonts.register_fonts()
    name = "Maximilian Alexander Konstantin von Hohenzollern-Sigmaringen-Wittelsbach"
    fitted = _fit_name(name, fonts.NAME.name, LAYOUT.text_right - LAYOUT.text_left)
    assert len(fitted.lines) == 2
    assert " ".join(fitted.lines) == name


def test_missing_glyphs_fall_back_to_noto_serif() -> None:
    fonts.register_fonts()
    # Pick a character Noto Serif has and Cormorant lacks (some Vietnamese and
    # rarer Latin letters), so the test does not depend on one specific glyph.
    sample = next(
        character
        for character in "ỹẞǅȘ"
        if not fonts.font_covers(fonts.NAME.name, character)
        and fonts.font_covers(fonts.NAME_FALLBACK.name, character)
    )
    assert fonts.font_for_text(fonts.NAME.name, f"Ada {sample}") == fonts.NAME_FALLBACK.name
    assert fonts.font_for_text(fonts.NAME.name, "Ada Lovelace") == fonts.NAME.name


def test_rendering_is_safe_from_several_threads(renderer: SecurityPrintRenderer) -> None:
    names = [f"Recipient Number {index}" for index in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(
            pool.map(lambda name: renderer.render(render_context(recipient_name=name)), names)
        )
    for name, pdf_bytes in zip(names, outputs, strict=True):
        assert name in extracted_text(pdf_bytes)

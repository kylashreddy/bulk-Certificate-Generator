"""Render the three reference certificates into samples/ (PDF + PNG preview).

Run with `make samples`. The cases cover the layout's stress points: a short name,
a very long name (shrink then wrap), and an accented name (glyph coverage).

It also cuts the seal out of each preview: samples/seal.png (README logo) and
samples/seals.png (three serials side by side, showing each seal is unique).
"""

from datetime import date
from pathlib import Path

import pypdfium2
from PIL import Image, ImageDraw

from certgen.rendering.design_tokens import LAYOUT, PAGE_HEIGHT
from certgen.rendering.protocol import RenderContext
from certgen.rendering.security_print import SecurityPrintRenderer

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
PREVIEW_SCALE = 2  # 144 dpi: sharp enough to judge hairlines
SEAL_OUTER_RADIUS = LAYOUT.seal_radius + 24  # rosette plus the circular microtext ring
LOGO_SIZE = 160
STRIP_SEAL_SIZE = 260

BASE = {
    "title": "Advanced Data Engineering",
    "achievement_line": "for successfully completing the twelve-week professional programme",
    "certificate_kind": "COMPLETION",
    "issued_on": date(2026, 10, 11),
    "issuer_name": "Northwind Academy",
    "signatory_name": "Dr. Amara Okafor",
    "signatory_title": "Director of Programmes",
}

CASES = {
    "short_name": ("Ada Lovelace", "BCG-2026-K7Q4-00001"),
    "long_name": (
        "Maximilian Alexander Konstantin von Hohenzollern-Sigmaringen-Wittelsbach",
        "BCG-2026-K7Q4-00002",
    ),
    "accented_name": ("Zoë Ångström-Núñez Łukasiewicz", "BCG-2026-K7Q4-00003"),
}


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    renderer = SecurityPrintRenderer()
    seals: list[Image.Image] = []
    for case_name, (recipient_name, serial) in CASES.items():
        context = RenderContext(
            recipient_name=recipient_name,
            serial=serial,
            verification_url=f"http://localhost:8000/api/v1/verify/sample-{case_name}",
            **BASE,  # type: ignore[arg-type]
        )
        pdf_path = SAMPLES_DIR / f"{case_name}.pdf"
        pdf_path.write_bytes(renderer.render(context))
        preview = pypdfium2.PdfDocument(pdf_path)[0].render(scale=PREVIEW_SCALE).to_pil()
        preview.save(SAMPLES_DIR / f"{case_name}.png")
        seals.append(cut_out_seal(preview))
        print(f"wrote {pdf_path.name} and {case_name}.png")

    seals[0].resize((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS).save(SAMPLES_DIR / "seal.png")
    seal_strip(seals).save(SAMPLES_DIR / "seals.png")
    print("wrote seal.png and seals.png")


def cut_out_seal(preview: Image.Image) -> Image.Image:
    """Crop the seal from a page preview, with a transparent circular mask so it
    sits cleanly on any README background (light or dark theme)."""
    centre_x = LAYOUT.seal_centre_x * PREVIEW_SCALE
    centre_y = (PAGE_HEIGHT - LAYOUT.seal_centre_y) * PREVIEW_SCALE
    radius = SEAL_OUTER_RADIUS * PREVIEW_SCALE
    box = (centre_x - radius, centre_y - radius, centre_x + radius, centre_y + radius)
    seal = preview.crop(tuple(round(edge) for edge in box)).convert("RGBA")
    mask = Image.new("L", seal.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, seal.size[0] - 1, seal.size[1] - 1), fill=255)
    seal.putalpha(mask)
    return seal


def seal_strip(seals: list[Image.Image]) -> Image.Image:
    gap = 24
    strip = Image.new(
        "RGBA", (len(seals) * STRIP_SEAL_SIZE + (len(seals) - 1) * gap, STRIP_SEAL_SIZE)
    )
    for index, seal in enumerate(seals):
        resized = seal.resize((STRIP_SEAL_SIZE, STRIP_SEAL_SIZE), Image.Resampling.LANCZOS)
        strip.paste(resized, (index * (STRIP_SEAL_SIZE + gap), 0), resized)
    return strip


if __name__ == "__main__":
    main()

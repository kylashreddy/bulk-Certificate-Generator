"""The "engraved security print" certificate, drawn with ReportLab (vector only).

Page anatomy, back to front:
  ivory paper -> faint guilloche wave field -> double hairline frame with microtext
  between the frames -> crop marks -> serial-derived rosette seal (left third) ->
  left-aligned text block (right two thirds) -> bottom row: serial, signatory,
  date, QR code.

Each layer is one small function so a design change touches one place, and all
measurements come from design_tokens.
"""

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass

from reportlab import rl_config
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color
from reportlab.pdfgen.canvas import Canvas

from certgen.rendering import fonts
from certgen.rendering.design_tokens import (
    FRAME,
    LAYOUT,
    OPACITY,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    PALETTE,
    ROSETTE,
    TYPE,
)
from certgen.rendering.protocol import RenderContext
from certgen.rendering.rosette import Point, ring_copies, rosette_parameters
from certgen.rendering.text_fitting import (
    FittedText,
    fit_lines,
    fit_single_line,
    fit_with_floor,
    text_width,
)

MICROTEXT_SEPARATOR = " · "  # middle dot


class SecurityPrintRenderer:
    def __init__(self) -> None:
        fonts.register_fonts()
        # Write compressed streams as raw binary instead of ASCII85 text: ~20% smaller
        # files and no slow base85 pass. ASCII85 only matters for 7-bit transports.
        rl_config.useA85 = 0

    def render(self, context: RenderContext) -> bytes:
        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1)
        canvas.setTitle(f"{context.title} - {context.recipient_name}")
        canvas.setAuthor(context.issuer_name)
        canvas.setSubject(f"Certificate {context.serial}")

        _paint_paper(canvas)
        _draw_wave_field(canvas)
        _draw_frames(canvas)
        _draw_microtext_border(canvas, context)
        _draw_crop_marks(canvas)
        _draw_seal(canvas, context)
        _draw_text_block(canvas, context)
        _draw_bottom_row(canvas, context)
        _draw_qr_code(canvas, context.verification_url)

        canvas.showPage()
        canvas.save()
        return buffer.getvalue()


# --- background and border -------------------------------------------------------


def _paint_paper(canvas: Canvas) -> None:
    canvas.setFillColor(PALETTE.paper)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)


def _draw_wave_field(canvas: Canvas) -> None:
    """Fine parallel sine waves, the anti-copy background of banknotes. Drawn at
    very low opacity so it reads as paper texture, not decoration."""
    inset = FRAME.inner_inset + 6
    canvas.saveState()
    canvas.setStrokeColor(PALETTE.guilloche)
    canvas.setStrokeAlpha(OPACITY.background_waves)
    canvas.setLineWidth(0.25)
    y = inset
    while y < PAGE_HEIGHT - inset:
        path = canvas.beginPath()
        x = inset
        path.moveTo(x, y + _wave_offset(x, y))
        while x < PAGE_WIDTH - inset:
            # 8pt steps: the waves' wavelength is ~160pt, so this is still smooth.
            x = min(x + 8, PAGE_WIDTH - inset)
            path.lineTo(x, y + _wave_offset(x, y))
        canvas.drawPath(path, stroke=1, fill=0)
        y += 6.5
    canvas.restoreState()


def _wave_offset(x: float, y: float) -> float:
    return 1.8 * math.sin(x / 26 + y / 47) + 0.9 * math.sin(x / 61 - y / 83)


def _draw_frames(canvas: Canvas) -> None:
    canvas.saveState()
    canvas.setStrokeColor(PALETTE.ink)
    canvas.setStrokeAlpha(OPACITY.frames)
    for inset, line_width in (
        (FRAME.outer_inset, FRAME.outer_line_width),
        (FRAME.inner_inset, FRAME.inner_line_width),
    ):
        canvas.setLineWidth(line_width)
        canvas.rect(inset, inset, PAGE_WIDTH - 2 * inset, PAGE_HEIGHT - 2 * inset)
    canvas.restoreState()


def _draw_microtext_border(canvas: Canvas, context: RenderContext) -> None:
    """3pt monospace text repeated along the band between the two frames. At arm's
    length it reads as a solid rule; under a loupe it reads TITLE · ISSUER."""
    unit = f"{context.title}{MICROTEXT_SEPARATOR}{context.issuer_name}{MICROTEXT_SEPARATOR}"
    unit = unit.upper()
    font_name = fonts.font_for_text(fonts.MONO.name, unit)
    band_middle = (FRAME.outer_inset + FRAME.inner_inset) / 2
    baseline_shift = TYPE.microtext_size * 0.35  # centres cap height on the band
    corner_clearance = band_middle + 6
    horizontal_length = PAGE_WIDTH - 2 * corner_clearance
    vertical_length = PAGE_HEIGHT - 2 * corner_clearance

    canvas.saveState()
    canvas.setFillColor(PALETTE.ink)
    canvas.setFillAlpha(OPACITY.microtext)
    canvas.setFont(font_name, TYPE.microtext_size)
    # (origin x, origin y, rotation, run length) for bottom, right, top, left sides.
    sides = (
        (corner_clearance, band_middle - baseline_shift, 0, horizontal_length),
        (PAGE_WIDTH - band_middle - baseline_shift, corner_clearance, 90, vertical_length),
        (
            PAGE_WIDTH - corner_clearance,
            PAGE_HEIGHT - band_middle + baseline_shift,
            180,
            horizontal_length,
        ),
        (band_middle + baseline_shift, PAGE_HEIGHT - corner_clearance, 270, vertical_length),
    )
    for origin_x, origin_y, rotation, length in sides:
        text, tracking = _justified_repeat(unit, font_name, TYPE.microtext_size, length)
        canvas.saveState()
        canvas.translate(origin_x, origin_y)
        canvas.rotate(rotation)
        _draw_tracked(canvas, 0, 0, text, font_name, TYPE.microtext_size, tracking)
        canvas.restoreState()
    canvas.restoreState()


def _justified_repeat(
    unit: str, font_name: str, font_size: float, length: float
) -> tuple[str, float]:
    """Whole repetitions of `unit` plus the letter-spacing that makes them fill
    `length` exactly, so no side of the border ends in a cut-off word."""
    unit_width = max(text_width(unit, font_name, font_size), 1.0)
    repetitions = max(int(length / unit_width), 1)
    text = (unit * repetitions).rstrip(MICROTEXT_SEPARATOR)
    spare = length - text_width(text, font_name, font_size)
    return text, max(spare, 0.0) / max(len(text) - 1, 1)


def _draw_crop_marks(canvas: Canvas) -> None:
    """Print-registration marks outside each corner of the outer frame."""
    canvas.saveState()
    canvas.setStrokeColor(PALETTE.ink)
    canvas.setLineWidth(FRAME.crop_mark_width)
    inset, gap, length = FRAME.outer_inset, FRAME.crop_mark_gap, FRAME.crop_mark_length
    for corner_x, direction_x in ((inset, -1), (PAGE_WIDTH - inset, 1)):
        for corner_y, direction_y in ((inset, -1), (PAGE_HEIGHT - inset, 1)):
            # Horizontal tick continues the frame's horizontal edge outwards ...
            start_x = corner_x + direction_x * gap
            canvas.line(start_x, corner_y, start_x + direction_x * length, corner_y)
            # ... and the vertical tick continues the vertical edge.
            start_y = corner_y + direction_y * gap
            canvas.line(corner_x, start_y, corner_x, start_y + direction_y * length)
    canvas.restoreState()


# --- the seal ----------------------------------------------------------------------


def _draw_seal(canvas: Canvas, context: RenderContext) -> None:
    parameters = rosette_parameters(context.serial)
    centre = (LAYOUT.seal_centre_x, LAYOUT.seal_centre_y)
    radius = LAYOUT.seal_radius

    canvas.saveState()
    canvas.setStrokeColor(PALETTE.guilloche)
    canvas.setLineWidth(ROSETTE.hairline_width)
    canvas.setStrokeAlpha(OPACITY.rosette_outer)
    _stroke_curves(canvas, ring_copies(parameters.outer, radius, parameters.rotation, centre))
    middle_radius = radius * ROSETTE.middle_radius_ratio
    _stroke_curves(
        canvas, ring_copies(parameters.middle, middle_radius, -parameters.rotation, centre)
    )

    canvas.setStrokeColor(PALETTE.ink)
    canvas.setStrokeAlpha(OPACITY.rosette_inner)
    canvas.setLineWidth(ROSETTE.inner_line_width)
    for ring_radius in (radius + 5, radius + 19):
        canvas.circle(centre[0], centre[1], ring_radius, stroke=1, fill=0)

    canvas.setStrokeColor(PALETTE.accent)
    inner_radius = radius * ROSETTE.inner_radius_ratio
    _stroke_curves(canvas, ring_copies(parameters.inner, inner_radius, parameters.rotation, centre))
    canvas.setFillColor(PALETTE.accent)
    canvas.setFillAlpha(1)
    canvas.circle(centre[0], centre[1], radius * ROSETTE.centre_dot_ratio, stroke=0, fill=1)
    canvas.restoreState()

    _draw_circular_microtext(canvas, context, centre, radius + 12)


def _stroke_curves(canvas: Canvas, curves: Sequence[Sequence[Point]]) -> None:
    path = canvas.beginPath()
    for curve in curves:
        path.moveTo(*curve[0])
        for point in curve[1:]:
            path.lineTo(*point)
    canvas.drawPath(path, stroke=1, fill=0)


def _draw_circular_microtext(
    canvas: Canvas, context: RenderContext, centre: Point, radius: float
) -> None:
    """Issuer and serial set around the seal, one character at a time, clockwise
    from the top, like the legend on a coin. A whole number of repetitions is used
    and the leftover space is shared between characters, so there is no seam."""
    unit = f"{context.issuer_name}{MICROTEXT_SEPARATOR}{context.serial}{MICROTEXT_SEPARATOR}"
    unit = unit.upper()
    font_name = fonts.font_for_text(fonts.MONO.name, unit)
    font_size = 4.6
    circumference = 2 * math.pi * radius
    unit_width = text_width(unit, font_name, font_size)
    repetitions = max(int(circumference / unit_width), 1)
    text = unit * repetitions
    spare = (circumference - text_width(text, font_name, font_size)) / len(text)

    canvas.saveState()
    canvas.setFillColor(PALETTE.ink)
    canvas.setFillAlpha(OPACITY.microtext)
    canvas.setFont(font_name, font_size)
    angle = math.pi / 2  # start at 12 o'clock
    for character in text:
        advance = text_width(character, font_name, font_size) + spare
        mid_angle = angle - (advance / 2) / radius
        canvas.saveState()
        canvas.translate(
            centre[0] + radius * math.cos(mid_angle), centre[1] + radius * math.sin(mid_angle)
        )
        canvas.rotate(math.degrees(mid_angle) - 90)
        canvas.drawCentredString(0, -font_size * 0.35, character)
        canvas.restoreState()
        angle -= advance / radius
    canvas.restoreState()


# --- text --------------------------------------------------------------------------


def _draw_tracked(
    canvas: Canvas, x: float, y: float, text: str, font_name: str, size: float, tracking: float
) -> None:
    """Letter-spaced text (ReportLab's drawString has no tracking parameter)."""
    text_object = canvas.beginText(x, y)
    text_object.setFont(font_name, size)
    text_object.setCharSpace(tracking)
    text_object.textOut(text)
    # Char spacing is part of the PDF text state and would leak into later text.
    text_object.setCharSpace(0)
    canvas.drawText(text_object)


def _draw_label(canvas: Canvas, x: float, y: float, text: str, small: bool = False) -> None:
    size = TYPE.small_label_size if small else TYPE.label_size
    tracking = TYPE.small_label_tracking if small else TYPE.label_tracking
    upper = text.upper()
    _draw_tracked(canvas, x, y, upper, fonts.font_for_text(fonts.LABEL.name, upper), size, tracking)


def _fit_name(name: str, font_name: str, width: float) -> FittedText:
    return (
        fit_single_line(name, font_name, TYPE.name_max_size, TYPE.name_min_size, width)
        or fit_lines(
            name, font_name, TYPE.name_two_line_max_size, TYPE.name_two_line_min_size, width, 2
        )
        or fit_with_floor(
            name, font_name, TYPE.name_two_line_min_size, TYPE.hard_minimum_size, width, 2
        )
    )


def _fit_block(
    text: str, font_name: str, max_size: float, min_size: float, width: float, max_lines: int
) -> FittedText:
    return fit_lines(text, font_name, max_size, min_size, width, max_lines) or fit_with_floor(
        text, font_name, min_size, TYPE.hard_minimum_size, width, max_lines
    )


@dataclass(frozen=True)
class _TextRun:
    text: str
    font_name: str
    font_size: float
    baseline: float  # relative to the block's top edge (0), negative is downwards
    alpha: float = 1.0
    tracking: float = 0.0


@dataclass(frozen=True)
class _Rule:
    y: float  # relative to the block's top edge
    length: float
    line_width: float
    colour: Color


def _layout_text_block(
    context: RenderContext, width: float
) -> tuple[list[_TextRun | _Rule], float]:
    """Stack the block top-down and return its pieces plus its total height. Laying
    out before drawing lets the block be centred on the seal whatever the name length."""
    pieces: list[_TextRun | _Rule] = []
    cursor = 0.0

    label = f"Certificate of {context.certificate_kind}".upper()
    cursor -= TYPE.label_size
    pieces.append(
        _TextRun(label, fonts.font_for_text(fonts.LABEL.name, label), TYPE.label_size, cursor,
                 tracking=TYPE.label_tracking)
    )  # fmt: skip
    pieces.append(_Rule(cursor - 11, 22, 0.8, PALETTE.accent))

    cursor -= 44
    pieces.append(
        _TextRun("This certifies that", fonts.ITALIC.name, TYPE.preamble_size, cursor,
                 alpha=OPACITY.secondary_text)
    )  # fmt: skip

    name_font = fonts.font_for_text(fonts.NAME.name, context.recipient_name)
    name = _fit_name(context.recipient_name, name_font, width)
    cursor -= 14 + name.font_size * 0.86
    cursor = _stack_lines(pieces, name, name_font, cursor)

    cursor -= 16
    pieces.append(_Rule(cursor, width, 0.45, PALETTE.guilloche))

    if context.achievement_line:
        italic_font = fonts.font_for_text(fonts.ITALIC.name, context.achievement_line)
        achievement = _fit_block(
            context.achievement_line, italic_font, TYPE.achievement_max_size,
            TYPE.achievement_min_size, width, TYPE.achievement_max_lines,
        )  # fmt: skip
        cursor -= 8 + achievement.font_size
        cursor = _stack_lines(
            pieces, achievement, italic_font, cursor, alpha=OPACITY.secondary_text + 0.12
        )

    title_font = fonts.font_for_text(fonts.NAME.name, context.title)
    title = _fit_block(
        context.title, title_font, TYPE.title_max_size, TYPE.title_min_size, width,
        TYPE.title_max_lines,
    )  # fmt: skip
    cursor -= 12 + title.font_size
    cursor = _stack_lines(pieces, title, title_font, cursor)

    awarded = f"Awarded by {context.issuer_name}".upper()
    cursor -= 24
    pieces.append(
        _TextRun(awarded, fonts.font_for_text(fonts.LABEL.name, awarded), TYPE.awarded_size,
                 cursor, alpha=OPACITY.secondary_text + 0.12, tracking=TYPE.small_label_tracking)
    )  # fmt: skip
    return pieces, -cursor


def _stack_lines(
    pieces: list[_TextRun | _Rule],
    fitted: FittedText,
    font_name: str,
    first_baseline: float,
    alpha: float = 1.0,
) -> float:
    """Append each line of `fitted` and return the baseline of the last one."""
    baseline = first_baseline
    for index, line in enumerate(fitted.lines):
        if index:
            baseline -= fitted.font_size * TYPE.name_line_gap
        pieces.append(_TextRun(line, font_name, fitted.font_size, baseline, alpha))
    return baseline


def _draw_text_block(canvas: Canvas, context: RenderContext) -> None:
    x = LAYOUT.text_left
    pieces, height = _layout_text_block(context, LAYOUT.text_right - LAYOUT.text_left)
    # Centre on the seal, but never rise above the design's top line.
    top = min(LAYOUT.seal_centre_y + height / 2, LAYOUT.text_top_limit)
    canvas.saveState()
    canvas.setFillColor(PALETTE.ink)
    for piece in pieces:
        if isinstance(piece, _Rule):
            canvas.setStrokeColor(piece.colour)
            canvas.setLineWidth(piece.line_width)
            canvas.line(x, top + piece.y, x + piece.length, top + piece.y)
            continue
        canvas.setFillAlpha(piece.alpha)
        if piece.tracking:
            _draw_tracked(
                canvas, x, top + piece.baseline, piece.text, piece.font_name,
                piece.font_size, piece.tracking,
            )  # fmt: skip
        else:
            canvas.setFont(piece.font_name, piece.font_size)
            canvas.drawString(x, top + piece.baseline, piece.text)
    canvas.restoreState()


def _draw_bottom_row(canvas: Canvas, context: RenderContext) -> None:
    value_baseline = LAYOUT.bottom_row_baseline + 12
    label_baseline = LAYOUT.bottom_row_baseline

    canvas.saveState()
    canvas.setFillColor(PALETTE.ink)

    # Signatory: a hairline to sign on, the name, then the role.
    x = LAYOUT.text_left
    canvas.setStrokeColor(PALETTE.ink)
    canvas.setLineWidth(0.5)
    rule_y = value_baseline + LAYOUT.signature_rule_offset
    canvas.line(x, rule_y, x + LAYOUT.signatory_column_width, rule_y)
    signatory_font = fonts.font_for_text(fonts.NAME.name, context.signatory_name)
    signatory = fit_with_floor(
        context.signatory_name,
        signatory_font,
        TYPE.signatory_name_size,
        TYPE.hard_minimum_size,
        LAYOUT.signatory_column_width,
        1,
    )
    canvas.setFont(signatory_font, signatory.font_size)
    canvas.drawString(x, value_baseline, signatory.lines[0])
    _draw_label(canvas, x, label_baseline, context.signatory_title, small=True)

    # Date of issue.
    # Mono, like the serial: Cormorant's old-style figures make "11" look like "II".
    canvas.setFont(fonts.MONO.name, TYPE.bottom_value_size)
    canvas.drawString(LAYOUT.date_column_x, value_baseline, _format_date(context))
    _draw_label(canvas, LAYOUT.date_column_x, label_baseline, "Date of issue", small=True)

    # Serial under the seal: the seal is derived from it, so they belong together.
    canvas.setFillColor(PALETTE.accent)
    canvas.setFont(fonts.MONO.name, TYPE.serial_size)
    canvas.drawCentredString(LAYOUT.seal_centre_x, value_baseline, context.serial)
    canvas.setFillColor(PALETTE.ink)
    label = "SERIAL NO."
    label_width = text_width(
        label, fonts.LABEL.name, TYPE.small_label_size, TYPE.small_label_tracking
    )
    _draw_label(canvas, LAYOUT.seal_centre_x - label_width / 2, label_baseline, label, small=True)
    canvas.restoreState()


def _format_date(context: RenderContext) -> str:
    # Built by hand rather than strftime("%B"), which follows the server's locale.
    months = (
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    )  # fmt: skip
    issued = context.issued_on
    return f"{issued.day:02d} {months[issued.month - 1][:3].upper()} {issued.year}"


def _draw_qr_code(canvas: Canvas, verification_url: str) -> None:
    widget = QrCodeWidget(verification_url, barLevel="M", barBorder=0)
    widget.barFillColor = PALETTE.ink
    left, bottom, right, top = widget.getBounds()
    size = LAYOUT.qr_size
    drawing = Drawing(
        size, size, transform=[size / (right - left), 0, 0, size / (top - bottom), 0, 0]
    )
    drawing.add(widget)
    x = LAYOUT.qr_right - size
    renderPDF.draw(drawing, canvas, x, LAYOUT.qr_bottom)

    canvas.saveState()
    canvas.setFillColor(PALETTE.ink)
    label = "SCAN TO VERIFY"
    label_width = text_width(
        label, fonts.LABEL.name, TYPE.small_label_size, TYPE.small_label_tracking
    )
    _draw_label(canvas, x + (size - label_width) / 2, LAYOUT.qr_bottom - 12, label, small=True)
    canvas.restoreState()

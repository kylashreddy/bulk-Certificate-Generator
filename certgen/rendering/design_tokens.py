"""Every colour, font size, margin and position used on the certificate.

Concept: "engraved security print", the visual language of banknotes and old share
certificates (guilloche rosettes, microtext borders, registration marks) set in a
modern, minimal, asymmetric layout. Units are PDF points (1/72 inch).
"""

from dataclasses import dataclass
from typing import Final

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4, landscape

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)  # 841.9 x 595.3


class Palette:
    # A plain class rather than a dataclass: Color objects are mutable, so they must
    # not be dataclass defaults. Treat these as constants.
    paper: Final[Color] = HexColor("#F4EFE4")  # warm ivory stock
    ink: Final[Color] = HexColor("#1C2541")  # deep blue-black engraving ink
    guilloche: Final[Color] = HexColor("#3A7D7B")  # teal, only ever as fine hairlines
    accent: Final[Color] = HexColor("#C4492D")  # vermilion: serial number and seal centre only


PALETTE = Palette()


@dataclass(frozen=True)
class Opacity:
    rosette_outer: float = 0.85
    rosette_inner: float = 0.75
    background_waves: float = 0.08
    frames: float = 0.9
    microtext: float = 0.75
    secondary_text: float = 0.72  # for "This certifies that" and small labels


OPACITY = Opacity()


@dataclass(frozen=True)
class Typography:
    label_size: float = 8.5
    label_tracking: float = 2.6  # letter-spacing for uppercase labels
    preamble_size: float = 16
    name_max_size: float = 48
    name_min_size: float = 30  # below this a name wraps to two lines instead
    name_two_line_max_size: float = 36
    name_two_line_min_size: float = 18
    name_line_gap: float = 1.05  # line height as a multiple of font size
    achievement_max_size: float = 16
    achievement_min_size: float = 11
    achievement_max_lines: int = 2
    title_max_size: float = 22
    title_min_size: float = 13
    title_max_lines: int = 2
    awarded_size: float = 8.5
    signatory_name_size: float = 13
    small_label_size: float = 6.5
    small_label_tracking: float = 1.8
    bottom_value_size: float = 9.5
    serial_size: float = 8.5
    microtext_size: float = 3.0
    hard_minimum_size: float = 6  # the last-resort floor: text never overflows


TYPE = Typography()


@dataclass(frozen=True)
class FrameGeometry:
    outer_inset: float = 26
    inner_inset: float = 36  # microtext runs in the 10pt band between the frames
    outer_line_width: float = 0.7
    inner_line_width: float = 0.35
    crop_mark_length: float = 11
    crop_mark_gap: float = 5  # distance between the outer frame corner and a mark
    crop_mark_width: float = 0.4


FRAME = FrameGeometry()


@dataclass(frozen=True)
class LayoutGeometry:
    # Left third: the seal. Right two thirds: the left-aligned text block.
    seal_centre_x: float = 190
    seal_centre_y: float = 344
    seal_radius: float = 112
    text_left: float = 352
    text_right: float = PAGE_WIDTH - 78
    text_top_limit: float = 500  # the text block is centred on the seal, but never above this
    bottom_row_baseline: float = 92
    signature_rule_offset: float = 17  # signature line sits this far above the name
    signatory_column_width: float = 200
    date_column_x: float = 352 + 236
    qr_size: float = 66
    qr_right: float = PAGE_WIDTH - 66
    qr_bottom: float = 66


LAYOUT = LayoutGeometry()


@dataclass(frozen=True)
class RosetteDesign:
    outer_copies_range: tuple[int, int] = (9, 14)
    outer_lobes_range: tuple[int, int] = (15, 27)
    middle_lobes_range: tuple[int, int] = (7, 13)
    middle_copies_range: tuple[int, int] = (7, 11)
    inner_lobes_range: tuple[int, int] = (5, 9)
    amplitude_range: tuple[float, float] = (0.16, 0.30)  # lobe depth as share of radius
    middle_radius_ratio: float = 0.68
    inner_radius_ratio: float = 0.36
    hairline_width: float = 0.3
    inner_line_width: float = 0.24
    points_per_lobe: int = 24
    centre_dot_ratio: float = 0.055


ROSETTE = RosetteDesign()

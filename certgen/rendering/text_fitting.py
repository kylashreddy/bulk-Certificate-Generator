"""Fit variable-length text (names, titles) into a fixed box without overflowing.

Strategy, in order of preference:
1. one line, shrinking from max_size down to min_size;
2. up to max_lines lines (balanced, so two lines have similar widths), shrinking
   within that range;
3. last resort: keep shrinking down to a hard floor. Validation caps names at 120
   characters, so this guarantees nothing ever runs off the page.
"""

from dataclasses import dataclass

from reportlab.pdfbase.pdfmetrics import stringWidth

SIZE_STEP = 0.5


@dataclass(frozen=True)
class FittedText:
    lines: list[str]
    font_size: float


def text_width(text: str, font_name: str, font_size: float, tracking: float = 0.0) -> float:
    return stringWidth(text, font_name, font_size) + tracking * max(len(text) - 1, 0)


def fit_single_line(
    text: str, font_name: str, max_size: float, min_size: float, width: float
) -> FittedText | None:
    natural = text_width(text, font_name, max_size)
    if natural <= width:
        return FittedText([text], max_size)
    # Width scales linearly with size, so the fitting size can be computed directly.
    size = _floor_to_step(max_size * width / natural)
    return FittedText([text], size) if size >= min_size else None


def fit_lines(
    text: str,
    font_name: str,
    max_size: float,
    min_size: float,
    width: float,
    max_lines: int,
) -> FittedText | None:
    size = max_size
    while size >= min_size:
        lines = wrap_balanced(text, font_name, size, width, max_lines)
        if lines is not None:
            return FittedText(lines, size)
        size -= SIZE_STEP
    return None


def fit_with_floor(
    text: str, font_name: str, start_size: float, floor: float, width: float, max_lines: int
) -> FittedText:
    """Never fails: shrinks to `floor`, then hard-breaks words if it must."""
    fitted = fit_lines(text, font_name, start_size, floor, width, max_lines)
    if fitted is not None:
        return fitted
    return FittedText(_hard_break(text, font_name, floor, width), floor)


def wrap_balanced(
    text: str, font_name: str, font_size: float, width: float, max_lines: int
) -> list[str] | None:
    """Greedy wrap to find how many lines are needed, then rebalance two-line
    results so the break falls near the middle (looks deliberate, not spilled)."""
    words = text.split()
    if any(text_width(word, font_name, font_size) > width for word in words):
        return None
    lines = _greedy_wrap(words, font_name, font_size, width)
    if len(lines) > max_lines:
        return None
    if len(lines) == 2:
        return _balanced_two_lines(words, font_name, font_size, width) or lines
    return lines


def _greedy_wrap(words: list[str], font_name: str, font_size: float, width: float) -> list[str]:
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if current and text_width(candidate, font_name, font_size) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _balanced_two_lines(
    words: list[str], font_name: str, font_size: float, width: float
) -> list[str] | None:
    best: tuple[float, list[str]] | None = None
    for split in range(1, len(words)):
        first, second = " ".join(words[:split]), " ".join(words[split:])
        widest = max(
            text_width(first, font_name, font_size), text_width(second, font_name, font_size)
        )
        if widest <= width and (best is None or widest < best[0]):
            best = (widest, [first, second])
    return best[1] if best else None


def _hard_break(text: str, font_name: str, font_size: float, width: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        if current and text_width(current + character, font_name, font_size) > width:
            lines.append(current.rstrip())
            current = character.lstrip()
        else:
            current += character
    if current:
        lines.append(current)
    return lines


def _floor_to_step(size: float) -> float:
    return int(size / SIZE_STEP) * SIZE_STEP

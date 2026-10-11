"""Procedural guilloche rosette, unique to each certificate serial.

The serial is hashed and a few bytes of the hash pick constrained parameters
(lobe counts, number of copies, lobe depth, rotation). The same serial always
yields the same seal; different serials yield visibly different ones, so the seal
works as a reproducible "fingerprint" of the certificate.

Each ring is a trochoid curve. With integer n:
    hypotrochoid:  x = a*cos(t) + b*cos(n*t),  y = a*sin(t) - b*sin(n*t)   (n+1 lobes)
    epitrochoid:   x = a*cos(t) - b*cos(n*t),  y = a*sin(t) - b*sin(n*t)   (n-1 lobes)
Both close after exactly one turn (t in [0, 2*pi]). Drawing many slightly rotated
copies of one curve produces the woven-hairline look of engraved security print.
"""

import hashlib
import math
from dataclasses import dataclass
from enum import StrEnum

from certgen.rendering.design_tokens import ROSETTE, RosetteDesign

Point = tuple[float, float]


class TrochoidKind(StrEnum):
    HYPO = "hypotrochoid"
    EPI = "epitrochoid"


@dataclass(frozen=True)
class RingParameters:
    kind: TrochoidKind
    frequency: int  # n in the formulas above
    copies: int  # rotated copies drawn to form the band
    amplitude: float  # b as a share of the ring radius (lobe depth)


@dataclass(frozen=True)
class RosetteParameters:
    outer: RingParameters
    middle: RingParameters
    inner: RingParameters
    rotation: float  # radians, so seals with similar rings still differ in phase


class _HashBytes:
    """Hands out successive bytes of a SHA-256 digest as bounded values."""

    def __init__(self, seed: str) -> None:
        self._digest = hashlib.sha256(seed.encode()).digest()
        self._index = 0

    def _next_byte(self) -> int:
        value = self._digest[self._index % len(self._digest)]
        self._index += 1
        return value

    def integer(self, bounds: tuple[int, int]) -> int:
        low, high = bounds
        return low + self._next_byte() % (high - low + 1)

    def fraction(self, bounds: tuple[float, float]) -> float:
        low, high = bounds
        return low + (high - low) * self._next_byte() / 255


def rosette_parameters(serial: str, design: RosetteDesign = ROSETTE) -> RosetteParameters:
    entropy = _HashBytes(serial)
    return RosetteParameters(
        outer=RingParameters(
            kind=TrochoidKind.EPI if entropy.integer((0, 1)) else TrochoidKind.HYPO,
            frequency=entropy.integer(design.outer_lobes_range),
            copies=entropy.integer(design.outer_copies_range),
            amplitude=entropy.fraction(design.amplitude_range),
        ),
        middle=RingParameters(
            kind=TrochoidKind.HYPO,
            frequency=entropy.integer(design.middle_lobes_range),
            copies=entropy.integer(design.middle_copies_range),
            amplitude=entropy.fraction(design.amplitude_range),
        ),
        inner=RingParameters(
            kind=TrochoidKind.EPI,
            frequency=entropy.integer(design.inner_lobes_range),
            copies=entropy.integer((5, 7)),
            # The inner ring is small; a fixed shallow depth keeps it from tangling.
            amplitude=0.22,
        ),
        rotation=entropy.fraction((0.0, 2 * math.pi)),
    )


def trochoid_points(
    ring: RingParameters,
    radius: float,
    phase: float,
    centre: Point,
    points_per_lobe: int = ROSETTE.points_per_lobe,
) -> list[Point]:
    """Sample one closed curve whose outermost extent is exactly `radius`."""
    b = radius * ring.amplitude
    a = radius - b  # a + b = radius, so every ring fits its circle precisely
    n = ring.frequency
    sign = 1.0 if ring.kind == TrochoidKind.HYPO else -1.0
    lobes = n + 1 if ring.kind == TrochoidKind.HYPO else n - 1
    samples = max(240, lobes * points_per_lobe)
    centre_x, centre_y = centre
    points: list[Point] = []
    for index in range(samples + 1):
        t = 2 * math.pi * index / samples
        x = a * math.cos(t) + sign * b * math.cos(n * t)
        y = a * math.sin(t) - b * math.sin(n * t)
        # Rotate the whole curve by `phase` to make each copy.
        points.append(
            (
                centre_x + x * math.cos(phase) - y * math.sin(phase),
                centre_y + x * math.sin(phase) + y * math.cos(phase),
            )
        )
    return points


def ring_copies(
    ring: RingParameters, radius: float, rotation: float, centre: Point
) -> list[list[Point]]:
    """All rotated copies of a ring. Copies are spread across one lobe's angular
    width, so the band interleaves evenly instead of bunching up."""
    lobes = ring.frequency + 1 if ring.kind == TrochoidKind.HYPO else ring.frequency - 1
    lobe_angle = 2 * math.pi / max(lobes, 1)
    return [
        trochoid_points(ring, radius, rotation + lobe_angle * copy / ring.copies, centre)
        for copy in range(ring.copies)
    ]

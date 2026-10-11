"""The seal's parameters are a deterministic, bounded function of the serial."""

import math

from certgen.rendering.design_tokens import ROSETTE
from certgen.rendering.rosette import rosette_parameters, trochoid_points


def test_same_serial_gives_the_same_rosette() -> None:
    assert rosette_parameters("BCG-2026-K7Q4-00042") == rosette_parameters("BCG-2026-K7Q4-00042")


def test_different_serials_give_different_rosettes() -> None:
    assert rosette_parameters("BCG-2026-K7Q4-00042") != rosette_parameters("BCG-2026-K7Q4-00043")


def test_rosettes_are_varied_across_many_serials() -> None:
    serials = [f"BCG-2026-K7Q4-{index:05d}" for index in range(1, 201)]
    distinct = {rosette_parameters(serial) for serial in serials}
    assert len(distinct) == len(serials)


def test_parameters_always_stay_inside_the_designed_ranges() -> None:
    for index in range(500):
        parameters = rosette_parameters(f"BCG-2026-ZZZZ-{index:05d}")
        low, high = ROSETTE.outer_lobes_range
        assert low <= parameters.outer.frequency <= high
        low, high = ROSETTE.outer_copies_range
        assert low <= parameters.outer.copies <= high
        low, high = ROSETTE.middle_lobes_range
        assert low <= parameters.middle.frequency <= high
        low, high = ROSETTE.inner_lobes_range
        assert low <= parameters.inner.frequency <= high
        for ring in (parameters.outer, parameters.middle):
            assert ROSETTE.amplitude_range[0] <= ring.amplitude <= ROSETTE.amplitude_range[1]
        assert 0 <= parameters.rotation <= 2 * math.pi


def test_curves_are_closed_and_fit_inside_their_radius() -> None:
    parameters = rosette_parameters("BCG-2026-K7Q4-00042")
    for ring in (parameters.outer, parameters.middle, parameters.inner):
        points = trochoid_points(ring, radius=100, phase=0.3, centre=(0, 0))
        first, last = points[0], points[-1]
        assert math.dist(first, last) < 1e-6
        assert max(math.hypot(x, y) for x, y in points) <= 100 + 1e-6

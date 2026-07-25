"""Tests for WhatIfDiff.direction_arrow()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfDiff


def _diff(delta_difference: float) -> WhatIfDiff:
    return WhatIfDiff(
        base_simulation_id=1,
        other_simulation_id=2,
        delta_difference=delta_difference,
    )


def test_arrow_up_for_positive_delta_difference() -> None:
    assert _diff(0.05).direction_arrow() == "↑"


def test_arrow_down_for_negative_delta_difference() -> None:
    assert _diff(-0.05).direction_arrow() == "↓"


def test_arrow_right_for_zero_delta_difference() -> None:
    assert _diff(0.0).direction_arrow() == "→"


def test_arrow_right_at_tolerance_boundary() -> None:
    assert _diff(1e-12).direction_arrow() == "→"
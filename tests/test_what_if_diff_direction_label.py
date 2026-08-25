"""Tests for WhatIfDiff.direction_label()."""
from __future__ import annotations

from app.schemas.what_if import WhatIfDiff


def _diff(delta_difference: float) -> WhatIfDiff:
    return WhatIfDiff(
        base_simulation_id=1,
        other_simulation_id=2,
        delta_difference=delta_difference,
    )


def test_direction_label_improvement_for_positive_delta_difference() -> None:
    assert _diff(0.05).direction_label() == "improvement"


def test_direction_label_regression_for_negative_delta_difference() -> None:
    assert _diff(-0.05).direction_label() == "regression"


def test_direction_label_neutral_for_zero_delta_difference() -> None:
    assert _diff(0.0).direction_label() == "neutral"


def test_direction_label_agrees_with_arrow_label_mapping() -> None:
    for delta in (0.1, -0.1, 0.0, 1e-12):
        label = _diff(delta).direction_label()
        if delta > 1e-9:
            assert label == "improvement"
        elif delta < -1e-9:
            assert label == "regression"
        else:
            assert label == "neutral"

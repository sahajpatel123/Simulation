"""Tests for WhatIfDiff delta-difference predicates."""
from __future__ import annotations

from app.schemas.what_if import WhatIfDiff


def _diff(delta_difference: float) -> WhatIfDiff:
    return WhatIfDiff(
        base_simulation_id=1,
        other_simulation_id=2,
        delta_difference=delta_difference,
    )


def test_has_positive_delta_true_for_positive() -> None:
    assert _diff(0.05).has_positive_delta() is True


def test_has_positive_delta_false_for_negative() -> None:
    assert _diff(-0.05).has_positive_delta() is False


def test_has_negative_delta_true_for_negative() -> None:
    assert _diff(-0.05).has_negative_delta() is True


def test_is_neutral_true_for_zero_and_tolerance_boundary() -> None:
    assert _diff(0.0).is_neutral() is True
    assert _diff(1e-12).is_neutral() is True


def test_predicates_are_mutually_exclusive_for_nonzero_deltas() -> None:
    for delta in (0.05, -0.05):
        diff = _diff(delta)
        flags = [diff.has_positive_delta(), diff.has_negative_delta(), diff.is_neutral()]
        assert sum(flags) == 1
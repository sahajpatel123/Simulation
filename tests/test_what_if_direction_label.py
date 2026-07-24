"""Tests for direction_label helper."""
from __future__ import annotations

from app.simulation.what_if import direction_label


def test_improvement_for_positive_delta() -> None:
    assert direction_label(0.1) == "improvement"


def test_regression_for_negative_delta() -> None:
    assert direction_label(-0.05) == "regression"


def test_neutral_for_zero_delta() -> None:
    assert direction_label(0.0) == "neutral"


def test_neutral_at_tolerance_boundary() -> None:
    assert direction_label(1e-12) == "neutral"
    assert direction_label(-1e-12) == "neutral"


def test_improvement_at_positive_tolerance_boundary() -> None:
    assert direction_label(1e-6) == "improvement"
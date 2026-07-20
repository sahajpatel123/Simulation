"""Regression tests for backend/app/simulation/calibration.py constants
and threshold semantics.

Why this exists: the magic numbers in calibration were inlined at each
call site, with no enforced relationship to the existing module-level
constants (MIN_OUTCOMES_FOR_CALIBRATION, RECENT_WINDOW, ADJUSTMENT_CAP).
A refactor hoisted them as named constants — these tests pin the
expected numeric values and the boundary behaviour so a future tweak
that silently flips a threshold fails loudly.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.simulation.calibration import (
    ADJUSTMENT_CAP,
    ACCURACY_VARIANCE_DAMPING,
    BIAS_OVER_PREDICTED_MAX,
    BIAS_UNDER_PREDICTED_MIN,
    CalibrationEngine,
    MARKOV_CLIP_HI,
    MARKOV_CLIP_LO,
    MARKOV_DELTA_MIN_ABS,
    MIN_OUTCOMES_FOR_CALIBRATION,
    RECENT_WINDOW,
    RELIABILITY_HIGH_ACCURACY,
    RELIABILITY_HIGH_SAMPLES,
    RELIABILITY_MEDIUM_ACCURACY,
    RELIABILITY_MEDIUM_SAMPLES,
    RETENTION_BOOST_ACCURACY_MAX,
    RETENTION_BOOST_DELTA,
    RETURN_CLIP_LO,
    TREND_DEGRADING_MAX,
    TREND_IMPROVING_MIN,
)


# ---------------------------------------------------------------------------
# Constants — the values are intentional design choices; pin them so
# silent edits fail this test rather than silently shifting calibration.
# ---------------------------------------------------------------------------


def test_calibration_constants_pinned() -> None:
    # Existing constants that drove this module before the hoist
    assert MIN_OUTCOMES_FOR_CALIBRATION == 3
    assert RECENT_WINDOW == 5
    assert ADJUSTMENT_CAP == pytest.approx(0.08)

    # Newly hoisted thresholds
    assert ACCURACY_VARIANCE_DAMPING == pytest.approx(2.0)
    assert BIAS_UNDER_PREDICTED_MIN == pytest.approx(5.0)
    assert BIAS_OVER_PREDICTED_MAX == pytest.approx(-5.0)

    assert RELIABILITY_HIGH_ACCURACY == pytest.approx(75.0)
    assert RELIABILITY_HIGH_SAMPLES == 10
    assert RELIABILITY_MEDIUM_ACCURACY == pytest.approx(55.0)
    assert RELIABILITY_MEDIUM_SAMPLES == 5

    assert TREND_IMPROVING_MIN == pytest.approx(4.0)
    assert TREND_DEGRADING_MAX == pytest.approx(-4.0)

    assert MARKOV_DELTA_MIN_ABS == pytest.approx(0.001)
    assert MARKOV_CLIP_LO == pytest.approx(0.05)
    assert MARKOV_CLIP_HI == pytest.approx(0.60)
    assert RETENTION_BOOST_DELTA == pytest.approx(0.02)
    assert RETENTION_BOOST_ACCURACY_MAX == pytest.approx(60.0)
    assert RETURN_CLIP_LO == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Boundary behaviour for the threshold methods
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> CalibrationEngine:
    return CalibrationEngine()


def test_outcome_accuracy_at_damping_extremes(engine: CalibrationEngine) -> None:
    """100 - 2*|variance| saturates at 0 for variance ≥ 50."""
    assert engine._outcome_accuracy(0.0) == 100.0
    assert engine._outcome_accuracy(None) is None
    # Variance 25 → accuracy = 100 - 50 = 50.0
    assert engine._outcome_accuracy(25.0) == 50.0
    # Variance 50 → accuracy = 100 - 100 = 0.0 (saturated)
    assert engine._outcome_accuracy(50.0) == 0.0


def test_bias_direction_thresholds(engine: CalibrationEngine) -> None:
    """Pinned ±5% bias direction cutoffs."""
    assert engine._bias_direction([]) == "NEUTRAL"
    # Strictly above +5 → UNDER_PREDICTED
    assert engine._bias_direction([6.0, 7.0]) == "UNDER_PREDICTED"
    # Strictly below -5 → OVER_PREDICTED
    assert engine._bias_direction([-6.0, -7.0]) == "OVER_PREDICTED"
    # Inside the deadband stays NEUTRAL
    assert engine._bias_direction([3.0, -3.0]) == "NEUTRAL"
    # Boundary points at exactly ±5 stay NEUTRAL
    assert engine._bias_direction([5.0]) == "NEUTRAL"
    assert engine._bias_direction([-5.0]) == "NEUTRAL"


def test_reliability_thresholds(engine: CalibrationEngine) -> None:
    """Tri-state reliability pinned to the documented cutoffs."""
    # INSUFFICIENT_DATA below MIN_OUTCOMES_FOR_CALIBRATION
    assert engine._reliability(0, 99.0) == "INSUFFICIENT_DATA"
    # HIGH requires BOTH high accuracy AND ≥10 samples
    assert engine._reliability(10, 80.0) == "HIGH"
    assert engine._reliability(10, 74.0) == "MEDIUM"  # accuracy fails
    assert engine._reliability(9, 80.0) == "MEDIUM"  # samples fail
    # MEDIUM is accurate enough OR has enough samples
    assert engine._reliability(MIN_OUTCOMES_FOR_CALIBRATION, RELIABILITY_MEDIUM_ACCURACY) == "MEDIUM"
    assert engine._reliability(RELIABILITY_MEDIUM_SAMPLES, 0.0) == "MEDIUM"
    # Below MEDIUM threshold on both axes → LOW
    assert engine._reliability(MIN_OUTCOMES_FOR_CALIBRATION, 1.0) == "LOW"


def _outcomes_with_scores(scores: list[float]) -> list[SimpleNamespace]:
    """Wrap bare scores in SimpleNamespace so _trend() can read .calibration_score."""
    return [SimpleNamespace(calibration_score=s) for s in scores]


def test_trend_thresholds(engine: CalibrationEngine) -> None:
    """Trend pinned to ±4-point recent-vs-overall delta.

    _trend() slices scores[:RECENT_WINDOW] as the 'recent' cohort, so
    to push delta positive the first RECENT_WINDOW outcomes must carry
    higher values than the rest of the list.
    """
    # Below MIN_OUTCOMES_FOR_CALIBRATION outcomes → INSUFFICIENT_DATA
    assert engine._trend([]) == ("INSUFFICIENT_DATA", 0.0)
    # All-equal → delta == 0 → STABLE
    direction, delta = engine._trend(_outcomes_with_scores([50.0] * 10))
    assert direction == "STABLE"
    assert delta == 0.0
    # recent=8, tail=0 → recent_avg=8, overall_avg=4 → delta=4 → STABLE (boundary)
    direction, delta = engine._trend(_outcomes_with_scores([8.0] * 5 + [0.0] * 5))
    assert direction == "STABLE"
    assert delta == pytest.approx(4.0)
    # recent=10, tail=0 → recent_avg=10, overall_avg=5 → delta=5 → IMPROVING
    direction, delta = engine._trend(_outcomes_with_scores([10.0] * 5 + [0.0] * 5))
    assert direction == "IMPROVING"
    assert delta == pytest.approx(5.0)

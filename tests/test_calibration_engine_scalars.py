"""Direction and bounds tests for the calibration scalar writer.

The Conductor multiplies architect metrics by ``correction_scalar``, so
the calibration engine must emit scalars that move predictions TOWARD
observed outcomes: ``> 1.0`` when founders beat the model (actual >
predicted) and ``< 1.0`` when the model over-predicted. These tests pin
the sign, the clamp bounds, and the no-op gate so the closed calibration
loop can never learn in the wrong direction.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.simulation.calibration_engine import (
    ALL_ARCHITECT_NAMES,
    CalibrationEngine,
    _calibration_scalar,
)
from app.simulation.correction_application import (
    MAX_CORRECTION_SCALAR,
    MIN_CORRECTION_SCALAR,
)


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def fetchall(self) -> list[object]:
        return self._rows


class _FakeDb:
    """Captures every execute() call; SELECTs return rows, writes record params."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self.calls: list[dict | None] = []
        self.commits = 0

    def execute(self, statement: object, params: dict | None = None) -> _FakeResult:
        self.calls.append(params)
        return _FakeResult(self._rows)

    def commit(self) -> None:
        self.commits += 1


def _upsert_params(db: _FakeDb) -> list[dict]:
    return [p for p in db.calls if p and "cs" in p]


# ── layer 2: systematic bias ────────────────────────────────────────────


def test_systematic_bias_lowers_scalar_when_model_over_predicts() -> None:
    # predicted 0.20, actual 0.10 -> wmean = -0.10 -> scalar must be < 1.0.
    rows = [
        SimpleNamespace(
            actual_conversion_rate=0.10,
            learning_weight=1.0,
            results_json={"mean_conversion_rate": 0.20},
        )
        for _ in range(10)
    ]
    db = _FakeDb(rows)

    CalibrationEngine().update_systematic_bias("saas", db)

    params = _upsert_params(db)
    assert len(params) == len(ALL_ARCHITECT_NAMES)
    assert float(params[0]["cs"]) == pytest.approx(1.0 / 1.1)


def test_systematic_bias_raises_scalar_when_founders_beat_model() -> None:
    # predicted 0.20, actual 0.30 -> wmean = +0.10 -> scalar must be > 1.0.
    rows = [
        SimpleNamespace(
            actual_conversion_rate=0.30,
            learning_weight=1.0,
            results_json={"mean_conversion_rate": 0.20},
        )
        for _ in range(10)
    ]
    db = _FakeDb(rows)

    CalibrationEngine().update_systematic_bias("saas", db)

    params = _upsert_params(db)
    assert len(params) == len(ALL_ARCHITECT_NAMES)
    assert float(params[0]["cs"]) == pytest.approx(1.0 / 0.9)


def test_systematic_bias_skips_write_within_noise_band() -> None:
    rows = [
        SimpleNamespace(
            actual_conversion_rate=0.201,
            learning_weight=1.0,
            results_json={"mean_conversion_rate": 0.20},
        )
        for _ in range(10)
    ]
    db = _FakeDb(rows)

    CalibrationEngine().update_systematic_bias("saas", db)

    assert _upsert_params(db) == []


# ── layer 3: structural patterns ────────────────────────────────────────


def test_structural_patterns_raises_scalar_when_founders_beat_model() -> None:
    # summary conversion 0.20, actual 0.30 -> wmean = +0.10 -> scalar > 1.0.
    rows = [
        SimpleNamespace(
            cluster_id="c1",
            primary_drop_trigger="PricingArchitect",
            conversion_rate=0.20,
            signal_quality=0.8,
            product_type="saas",
            actual_conversion_rate=0.30,
            learning_weight=1.0,
        )
        for _ in range(30)
    ]
    db = _FakeDb(rows)

    CalibrationEngine().update_structural_patterns(db)

    params = _upsert_params(db)
    assert len(params) == 1
    assert float(params[0]["cs"]) == pytest.approx(1.0 / 0.9)


def test_structural_patterns_lowers_scalar_when_model_over_predicts() -> None:
    # summary conversion 0.30, actual 0.20 -> wmean = -0.10 -> scalar < 1.0.
    rows = [
        SimpleNamespace(
            cluster_id="c1",
            primary_drop_trigger="PricingArchitect",
            conversion_rate=0.30,
            signal_quality=0.8,
            product_type="saas",
            actual_conversion_rate=0.20,
            learning_weight=1.0,
        )
        for _ in range(30)
    ]
    db = _FakeDb(rows)

    CalibrationEngine().update_structural_patterns(db)

    params = _upsert_params(db)
    assert len(params) == 1
    assert float(params[0]["cs"]) == pytest.approx(1.0 / 1.1)


# ── helper bounds ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("wmean", "expected"),
    [
        (0.95, MAX_CORRECTION_SCALAR),
        (1.0, MAX_CORRECTION_SCALAR),  # division-by-zero guard
        (-1.0, MIN_CORRECTION_SCALAR),  # 1 / 2 == lower bound
        (-2.0, MIN_CORRECTION_SCALAR),  # malformed beyond the domain
        (0.0, 1.0),
    ],
)
def test_calibration_scalar_helper_clamps_to_safe_bounds(
    wmean: float,
    expected: float,
) -> None:
    assert _calibration_scalar(wmean) == expected


def test_calibration_scalar_helper_ignores_non_finite_errors() -> None:
    assert _calibration_scalar(float("nan")) == 1.0
    assert _calibration_scalar(float("inf")) == 1.0

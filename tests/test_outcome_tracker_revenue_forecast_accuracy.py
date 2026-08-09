"""Tests for historical revenue-forecast accuracy verification."""
from __future__ import annotations

import math
import sys
import types
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub

from app.schemas.outcome_tracker import (
    OutcomeTrackerRevenueForecastAccuracyOut,
)
from app.simulation.outcome_tracker_revenue_forecast_accuracy import (
    BIAS_BALANCED,
    BIAS_INSUFFICIENT_DATA,
    BIAS_OVER_PREDICTS,
    BIAS_UNDER_PREDICTS,
    VERDICT_ACCURATE,
    VERDICT_INSUFFICIENT_DATA,
    build_outcome_tracker_revenue_forecast_accuracy,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _row(rid: int, *, day: float, revenue: float) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": 7,
        "simulation_id": 12,
        "recorded_at": (BASE + timedelta(days=day)).isoformat(),
        "actual_conversion_rate": None,
        "actual_revenue": revenue,
        "predicted_conversion_rate": None,
        "predicted_revenue": None,
        "variance": None,
        "notes": None,
    }


def _linear_rows(
    start: float = 100_000.0,
    step: float = -500.0,
    every: float = 30.0,
) -> list[dict[str, Any]]:
    return [
        _row(i + 1, day=day, revenue=start + step * day)
        for i, day in enumerate(range(0, 181, int(every)))
    ]


def _call(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int = 7,
    predicted: float | None = None,
) -> dict[str, Any]:
    return build_outcome_tracker_revenue_forecast_accuracy(
        rows,
        project_id=project_id,
        predicted_revenue=predicted,
    )


# ---------------------------------------------------------------------------
# Pure builder — insufficient data
# ---------------------------------------------------------------------------


def test_empty_rows_are_insufficient() -> None:
    out = _call(None, predicted=50_000.0)
    assert out["project_id"] == 7
    assert out["total_verifications"] == 0
    assert out["overall_verdict"] == VERDICT_INSUFFICIENT_DATA
    assert out["overall_bias_direction"] == BIAS_INSUFFICIENT_DATA
    assert out["confidence"] == "INSUFFICIENT_DATA"
    assert len(out["horizons"]) == 3
    assert all(h["sample_count"] == 0 for h in out["horizons"])
    assert [h["horizon_days"] for h in out["horizons"]] == [30, 60, 90]


def test_single_point_is_insufficient() -> None:
    out = _call([_row(1, day=0.0, revenue=50_000.0)], predicted=50_000.0)
    assert out["total_verifications"] == 0
    assert out["overall_verdict"] == VERDICT_INSUFFICIENT_DATA


def test_short_span_cannot_verify_any_horizon() -> None:
    """Three checkpoints over two days never reach a 30-day deadline."""
    rows = [
        _row(1, day=0.0, revenue=50_000.0),
        _row(2, day=1.0, revenue=60_000.0),
        _row(3, day=2.0, revenue=70_000.0),
    ]
    out = _call(rows, predicted=50_000.0)
    assert out["total_verifications"] == 0
    assert out["overall_verdict"] == VERDICT_INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Pure builder — perfect and biased series
# ---------------------------------------------------------------------------


def test_perfect_linear_series_scores_accurate() -> None:
    """A series that follows a straight line must verify as near-perfect.

    Uses a declining line so the projections stay below the forecast
    saturation ceiling (which would otherwise cap a strongly rising series
    exactly like the production forecast does).
    """
    out = _call(_linear_rows(), predicted=50_000.0)
    assert out["total_verifications"] == 12
    assert out["overall_verdict"] == VERDICT_ACCURATE
    assert out["overall_bias_direction"] == BIAS_BALANCED
    assert out["overall_accuracy_score"] >= 99.0
    assert out["overall_mean_abs_error"] is not None
    assert out["overall_mean_abs_error"] < 0.001
    assert out["overall_mean_abs_pct_error"] is not None
    assert out["overall_mean_abs_pct_error"] == pytest.approx(0.0)
    assert out["confidence"] == "HIGH"

    by_horizon = {h["horizon_days"]: h for h in out["horizons"]}
    assert by_horizon[30]["sample_count"] == 5
    assert by_horizon[60]["sample_count"] == 4
    assert by_horizon[90]["sample_count"] == 3
    for horizon in by_horizon.values():
        assert horizon["within_tolerance_rate"] == 1.0
        assert horizon["mean_abs_pct_error"] is not None
        assert horizon["mean_abs_pct_error"] < 0.001
        assert horizon["accuracy_score"] >= 99.0


def test_decelerating_series_is_over_predicted() -> None:
    """Actuals that stall after a strong early trend must flag over-prediction."""
    rows = [
        _row(1, day=0.0, revenue=50_000.0),
        _row(2, day=30.0, revenue=110_000.0),
        _row(3, day=60.0, revenue=110_000.0),
        _row(4, day=90.0, revenue=90_000.0),
        _row(5, day=120.0, revenue=80_000.0),
        _row(6, day=150.0, revenue=70_000.0),
    ]
    out = _call(rows, predicted=50_000.0)
    assert out["total_verifications"] >= 4
    assert out["overall_bias_direction"] == BIAS_OVER_PREDICTS
    assert out["overall_bias"] is not None and out["overall_bias"] > 10_000.0
    assert out["overall_accuracy_score"] < 90.0
    assert out["overall_verdict"] in ("MODERATE", "IMPRECISE")


def test_accelerating_series_is_under_predicted() -> None:
    """Actuals that accelerate past the fitted trend must flag under-prediction."""
    rows = [
        _row(1, day=0.0, revenue=5_000.0),
        _row(2, day=30.0, revenue=6_000.0),
        _row(3, day=60.0, revenue=10_000.0),
        _row(4, day=90.0, revenue=17_000.0),
        _row(5, day=120.0, revenue=27_000.0),
        _row(6, day=150.0, revenue=40_000.0),
    ]
    out = _call(rows, predicted=50_000.0)
    assert out["total_verifications"] >= 4
    assert out["overall_bias_direction"] == BIAS_UNDER_PREDICTS
    assert out["overall_bias"] is not None and out["overall_bias"] < -2_000.0


# ---------------------------------------------------------------------------
# Pure builder — robustness
# ---------------------------------------------------------------------------


def test_malformed_rows_are_dropped() -> None:
    rows = [
        {"id": 1, "recorded_at": None, "actual_revenue": 50_000.0},
        {"id": 2, "recorded_at": "not-a-timestamp", "actual_revenue": 50_000.0},
        {"id": 3, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_revenue": "bad"},
        {"id": 4, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_revenue": float("nan")},
        {"id": 5, "recorded_at": "2026-01-01T00:00:00+00:00", "actual_revenue": True},
        _row(6, day=0.0, revenue=100_000.0),
        _row(7, day=30.0, revenue=85_000.0),
        _row(8, day=60.0, revenue=70_000.0),
        _row(9, day=90.0, revenue=55_000.0),
        _row(10, day=120.0, revenue=40_000.0),
        _row(11, day=150.0, revenue=25_000.0),
        _row(12, day=180.0, revenue=10_000.0),
    ]
    clean = _call(
        [_row(6, day=0.0, revenue=100_000.0), _row(7, day=30.0, revenue=85_000.0),
         _row(8, day=60.0, revenue=70_000.0), _row(9, day=90.0, revenue=55_000.0),
         _row(10, day=120.0, revenue=40_000.0), _row(11, day=150.0, revenue=25_000.0),
         _row(12, day=180.0, revenue=10_000.0)],
        predicted=50_000.0,
    )
    out = _call(rows, predicted=50_000.0)
    assert out["total_verifications"] == clean["total_verifications"] == 12


def test_duplicate_timestamps_keep_last_row() -> None:
    rows = [
        _row(1, day=0.0, revenue=100_000.0),
        _row(2, day=30.0, revenue=85_000.0),
        _row(3, day=60.0, revenue=70_000.0),
        _row(4, day=90.0, revenue=55_000.0),
        _row(5, day=120.0, revenue=40_000.0),
        _row(6, day=150.0, revenue=25_000.0),
        _row(7, day=180.0, revenue=10_000.0),
        _row(8, day=180.0, revenue=20_000.0),  # same timestamp, later revenue wins
    ]
    expected = [
        _row(1, day=0.0, revenue=100_000.0),
        _row(2, day=30.0, revenue=85_000.0),
        _row(3, day=60.0, revenue=70_000.0),
        _row(4, day=90.0, revenue=55_000.0),
        _row(5, day=120.0, revenue=40_000.0),
        _row(6, day=150.0, revenue=25_000.0),
        _row(7, day=180.0, revenue=20_000.0),
    ]
    out = _call(rows, predicted=50_000.0)
    exp = _call(expected, predicted=50_000.0)
    assert out["total_verifications"] == exp["total_verifications"] == 12
    assert out["overall_accuracy_score"] == exp["overall_accuracy_score"]
    assert out["overall_bias_direction"] == exp["overall_bias_direction"]


def test_extreme_values_stay_finite_and_bounded() -> None:
    """Zero actuals and near-ceiling revenue must not produce NaN scores."""
    rows = [
        _row(1, day=0.0, revenue=10_000.0),
        _row(2, day=30.0, revenue=0.0),
        _row(3, day=60.0, revenue=0.0),
        _row(4, day=90.0, revenue=100_000.0),
        _row(5, day=120.0, revenue=100_000.0),
        _row(6, day=150.0, revenue=100_000.0),
        _row(7, day=180.0, revenue=100_000.0),
    ]
    out = _call(rows, predicted=50_000.0)
    for horizon in out["horizons"]:
        for key in (
            "mean_abs_error",
            "mean_abs_pct_error",
            "bias",
            "accuracy_score",
            "within_tolerance_rate",
        ):
            value = horizon[key]
            if value is not None:
                assert math.isfinite(value)
        if horizon["accuracy_score"] is not None:
            assert 0.0 <= horizon["accuracy_score"] <= 100.0
    assert math.isfinite(out["overall_accuracy_score"] or 0.0)


# ---------------------------------------------------------------------------
# Pure builder — bounded lookahead
# ---------------------------------------------------------------------------


def test_sparse_series_does_not_verify_against_far_late_actuals() -> None:
    """A 30-day forecast must not be scored against an actual 150 days late."""
    rows = [
        _row(1, day=0.0, revenue=5_000.0),
        _row(2, day=30.0, revenue=8_000.0),
        _row(3, day=60.0, revenue=11_000.0),
        _row(4, day=210.0, revenue=20_000.0),
    ]
    out = _call(rows, predicted=5_000.0)
    by_horizon = {h["horizon_days"]: h for h in out["horizons"]}
    assert by_horizon[30]["sample_count"] == 1
    assert by_horizon[60]["sample_count"] == 0
    assert by_horizon[90]["sample_count"] == 0
    assert out["total_verifications"] == 1
    assert out["overall_verdict"] == VERDICT_INSUFFICIENT_DATA


def test_checkpoint_within_grace_still_verifies_horizon() -> None:
    """A checkpoint 15 days past the 30-day deadline is still a valid actual."""
    rows = [
        _row(1, day=0.0, revenue=5_000.0),
        _row(2, day=30.0, revenue=8_000.0),
        _row(3, day=75.0, revenue=9_000.0),
    ]
    out = _call(rows, predicted=5_000.0)
    by_horizon = {h["horizon_days"]: h for h in out["horizons"]}
    assert by_horizon[30]["sample_count"] == 1
    # The production saturation ceiling caps the projection at
    # max(5_000, 8_000) * 1.02 = 8_160, so the honest error vs 9_000 is
    # ₹840 — the verifier must score the capped production forecast.
    assert by_horizon[30]["mean_abs_error"] == pytest.approx(840.0)
    assert by_horizon[30]["within_tolerance_rate"] == 1.0
    assert by_horizon[60]["sample_count"] == 0
    assert by_horizon[90]["sample_count"] == 0


def test_sparse_gap_excludes_only_misaligned_horizon_checks() -> None:
    """A 120-day logging gap drops 30-day checks across it but keeps 90-day ones."""
    rows = [
        _row(i + 1, day=day, revenue=100_000.0 - 500.0 * day)
        for i, day in enumerate((0, 30, 60, 90, 210, 240, 270, 300))
    ]
    out = _call(rows, predicted=50_000.0)
    by_horizon = {h["horizon_days"]: h for h in out["horizons"]}
    assert by_horizon[30]["sample_count"] == 5
    assert by_horizon[60]["sample_count"] == 3
    assert by_horizon[90]["sample_count"] == 2
    assert out["total_verifications"] == 10


def test_schema_accepts_builder_payload() -> None:
    out = OutcomeTrackerRevenueForecastAccuracyOut(
        **_call(_linear_rows(), predicted=50_000.0)
    )
    assert out.project_id == 7
    assert out.total_verifications == 12
    assert len(out.horizons) == 3
    assert out.horizons[0].horizon_days == 30


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def filter(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def order_by(self, *args: Any, **kwargs: Any) -> _FakeQuery:
        return self

    def first(self) -> Any:
        return self._items[0] if self._items else None

    def all(self) -> list[Any]:
        return self._items


class _FakeSimulation:
    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.id = 12
        self.results_json = results if results is not None else {"mean_revenue": 50_000.0}


class _FakeSession:
    def __init__(
        self,
        *,
        rows: list[Any] | None = None,
        sim: _FakeSimulation | None = None,
        project_items: list[Any] | None = None,
    ) -> None:
        self._rows = rows if rows is not None else []
        self._sim = sim
        self._project_items = project_items if project_items is not None else [object()]

    def query(self, model: Any, *args: Any, **kwargs: Any) -> _FakeQuery:
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery(self._project_items)
        if name == "Simulation":
            return _FakeQuery([self._sim] if self._sim is not None else [])
        if name == "OutcomeTracker":
            return _FakeQuery(self._rows)
        return _FakeQuery([])


def _make_tracker_row(
    rid: int,
    *,
    revenue: float,
    day: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid,
        project_id=7,
        simulation_id=12,
        recorded_at=BASE + timedelta(days=day),
        actual_conversion_rate=None,
        actual_revenue=revenue,
        predicted_conversion_rate=None,
        predicted_revenue=None,
        variance=None,
        notes=None,
    )


def _call_route(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_revenue_forecast_accuracy(
        project_id=7,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_route_returns_accuracy_with_sim_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(i, revenue=100_000.0 - 500.0 * day, day=day)
            for i, day in enumerate(range(0, 181, 30))
        ],
        sim=_FakeSimulation(results={"mean_revenue": 50_000.0}),
    )
    out = _call_route(session=session)
    assert out.project_id == 7
    assert out.total_verifications == 12
    assert out.overall_verdict == VERDICT_ACCURATE
    assert len(out.horizons) == 3


def test_route_falls_back_to_row_prediction_when_no_simulation() -> None:
    rows = [
        _make_tracker_row(i, revenue=100_000.0 - 500.0 * day, day=day)
        for i, day in enumerate(range(0, 181, 30))
    ]
    for row in rows:
        row.predicted_revenue = 50_000.0
    session = _FakeSession(rows=rows, sim=None)
    out = _call_route(session=session)
    assert out.overall_verdict == VERDICT_ACCURATE


def test_route_empty_tracker_is_insufficient() -> None:
    out = _call_route(session=_FakeSession(rows=[]))
    assert out.total_verifications == 0
    assert out.overall_verdict == VERDICT_INSUFFICIENT_DATA


def test_route_requires_project_ownership() -> None:
    session = _FakeSession(project_items=[])
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session, user_id=42)
    assert exc.value.status_code == 404

"""Tests for the post-launch revenue trajectory forecast feature."""
from __future__ import annotations

import math
import sys
import types
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = razorpay_stub


def _row(
    rid: int,
    *,
    recorded_at: str,
    actual: float | None,
) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": 7,
        "simulation_id": 12,
        "recorded_at": recorded_at,
        "actual_conversion_rate": None,
        "actual_revenue": actual,
        "predicted_conversion_rate": None,
        "predicted_revenue": None,
        "variance": None,
        "notes": None,
    }


def _call_forecast(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int = 7,
    predicted: float | None = None,
) -> dict[str, Any]:
    from app.simulation.outcome_tracker_revenue_forecast import (
        build_outcome_tracker_revenue_forecast,
    )

    return build_outcome_tracker_revenue_forecast(
        rows,
        project_id=project_id,
        predicted_revenue=predicted,
    )


# ---------------------------------------------------------------------------
# Pure helper — insufficient data
# ---------------------------------------------------------------------------


def test_revenue_forecast_empty_rows_is_insufficient() -> None:
    out = _call_forecast(None, predicted=1000.0)
    assert out["project_id"] == 7
    assert out["sample_count"] == 0
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["trend_label"] == "INSUFFICIENT_DATA"
    assert out["confidence"] == "INSUFFICIENT_DATA"
    assert out["forecasts"] == []
    assert out["days_to_target"] is None


def test_revenue_forecast_single_point_is_insufficient() -> None:
    rows = [_row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0)]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 1
    assert out["latest_revenue"] == 100.0
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["forecasts"] == []


def test_revenue_forecast_skips_malformed_rows() -> None:
    rows = [
        {"id": 1, "recorded_at": None, "actual_revenue": 100.0},
        {
            "id": 2,
            "recorded_at": "not-a-timestamp",
            "actual_revenue": 200.0,
        },
        {
            "id": 3,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_revenue": "bad",
        },
        {
            "id": 4,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_revenue": float("nan"),
        },
        {
            "id": 5,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_revenue": True,
        },
        _row(6, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(7, recorded_at="2026-08-15T00:00:00+00:00", actual=400.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 2
    assert out["span_days"] == 14.0
    assert out["latest_revenue"] == 400.0


def test_revenue_forecast_sorts_out_of_order_rows() -> None:
    rows = [
        _row(1, recorded_at="2026-08-20T00:00:00+00:00", actual=500.0),
        _row(2, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(3, recorded_at="2026-08-10T00:00:00+00:00", actual=250.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 3
    assert out["span_days"] == 19.0
    assert out["latest_revenue"] == 500.0
    # The 30-day projection is capped at the 1.02x ceiling (1020), which
    # keeps the verdict inside the on-track band rather than above target.
    assert out["verdict"] == "ON_TRACK"


def test_revenue_forecast_deduplicates_same_timestamp_keeping_latest() -> None:
    rows = [
        {
            "id": 1,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_revenue": 100.0,
        },
        {
            "id": 2,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_revenue": 500.0,
        },
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=500.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 2
    assert out["latest_revenue"] == 500.0
    assert out["verdict"] == "STALLED"


def test_revenue_forecast_all_points_same_day_is_insufficient() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-01T00:00:00+00:00", actual=200.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 1
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_revenue_forecast_parses_z_suffix_and_naive_datetimes() -> None:
    rows = [
        {
            "id": 1,
            "recorded_at": "2026-08-01T00:00:00Z",
            "actual_revenue": 100.0,
        },
        {
            "id": 2,
            "recorded_at": datetime(2026, 8, 15, 0, 0),
            "actual_revenue": 300.0,
        },
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 2
    assert out["span_days"] == 14.0


# ---------------------------------------------------------------------------
# Pure helper — verdicts and projections
# ---------------------------------------------------------------------------


def test_revenue_forecast_on_track_rising_trajectory() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=180.0),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=260.0),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=340.0),
    ]
    out = _call_forecast(rows, predicted=400.0)
    assert out["verdict"] == "ON_TRACK"
    assert out["trend_label"] == "CONVERGING"
    assert out["confidence"] == "HIGH"
    assert out["slope_per_day"] > 0.0
    assert out["r_squared"] is not None and out["r_squared"] >= 0.5
    assert [f["horizon_days"] for f in out["forecasts"]] == [30, 60, 90]
    assert all(
        f["projected_revenue"] <= out["ceiling_revenue"]
        for f in out["forecasts"]
    )
    assert out["days_to_target"] is not None and out["days_to_target"] > 0
    assert out["narrative"]
    assert any(s["label"] == "days_to_target" for s in out["key_signals"])


def test_revenue_forecast_latest_already_at_target_is_above() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=400.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=1000.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["verdict"] == "ABOVE_TARGET"
    assert out["days_to_target"] is None
    assert "already meets or exceeds" in out["narrative"]


def test_revenue_forecast_projected_above_target_narrative_is_accurate() -> None:
    # An earlier checkpoint peaked above the prediction and the recent
    # trend is rising again, so the verdict is ABOVE_TARGET based on the
    # 30-day projection even though the latest actual is still below the
    # target. The narrative must not claim the latest actual already
    # meets or exceeds the prediction.
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=600.0),
        _row(2, recorded_at="2026-08-02T00:00:00+00:00", actual=1200.0),
        _row(3, recorded_at="2026-08-03T00:00:00+00:00", actual=700.0),
        _row(4, recorded_at="2026-08-04T00:00:00+00:00", actual=800.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["verdict"] == "ABOVE_TARGET"
    assert out["latest_revenue"] < out["predicted_revenue"]
    assert out["forecasts"][0]["projected_revenue"] >= 1100.0
    assert "already meets or exceeds" not in out["narrative"]
    assert "still below the predicted" in out["narrative"]
    assert "above target" in out["narrative"]


def test_revenue_forecast_steep_rise_is_capped_at_ceiling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=500.0),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=1500.0),
    ]
    out = _call_forecast(rows, predicted=2000.0)
    # The saturation ceiling (1.02x the target) prevents a steep short-term
    # slope from claiming an above-target projection.
    assert out["verdict"] == "ON_TRACK"
    assert (
        out["forecasts"][0]["projected_revenue"]
        == out["ceiling_revenue"]
    )


def test_revenue_forecast_shallow_rise_is_below_target() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=110.0),
        _row(3, recorded_at="2026-08-21T00:00:00+00:00", actual=120.0),
    ]
    out = _call_forecast(rows, predicted=400.0)
    assert out["verdict"] == "BELOW_TARGET"
    assert out["forecasts"][0]["projected_revenue"] < 360.0


def test_revenue_forecast_flat_below_target_is_stalled() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=200.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=200.0),
    ]
    out = _call_forecast(rows, predicted=500.0)
    assert out["verdict"] == "STALLED"
    assert out["trend_label"] == "FLAT"
    assert out["slope_per_day"] == 0.0
    assert out["r_squared"] == 1.0
    assert out["days_to_target"] is None
    assert out["confidence"] == "LOW"


def test_revenue_forecast_flat_series_over_weeks_is_high_confidence() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=200.0),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=200.0),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=200.0),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=200.0),
    ]
    out = _call_forecast(rows, predicted=500.0)
    assert out["r_squared"] == 1.0
    assert out["confidence"] == "HIGH"
    assert out["trend_label"] == "FLAT"
    assert out["verdict"] == "STALLED"


def test_revenue_forecast_declining_trend_narrative_says_falling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=1000.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=600.0),
    ]
    out = _call_forecast(rows, predicted=5000.0)
    assert out["verdict"] == "STALLED"
    assert out["trend_label"] == "DECLINING"
    assert "falling" in out["narrative"]
    assert "has not improved" not in out["narrative"]


def test_revenue_forecast_narrative_pluralizes_single_day() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=1000.0),
        _row(2, recorded_at="2026-08-02T00:00:00+00:00", actual=3000.0),
    ]
    out = _call_forecast(rows, predicted=5000.0)
    assert out["days_to_target"] == 1.0
    assert "~1 day." in out["narrative"]
    assert "~1 days" not in out["narrative"]


def test_revenue_forecast_without_target_reports_trend_but_no_verdict() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=400.0),
    ]
    out = _call_forecast(rows, predicted=None)
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["trend_label"] == "CONVERGING"
    assert len(out["forecasts"]) == 3
    assert out["days_to_target"] is None
    assert out["predicted_revenue"] is None


def test_revenue_forecast_zero_prediction_is_treated_as_no_target() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=400.0),
    ]
    out = _call_forecast(rows, predicted=0.0)
    assert out["predicted_revenue"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_revenue_forecast_projections_are_capped_at_ceiling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-02T00:00:00+00:00", actual=200.0),
    ]
    out = _call_forecast(rows, predicted=2000.0)
    ceiling = out["ceiling_revenue"]
    assert ceiling is not None and ceiling > 0.0
    assert all(
        f["projected_revenue"] <= ceiling for f in out["forecasts"]
    )


def test_revenue_forecast_medium_confidence_with_three_points() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=200.0),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=300.0),
        _row(3, recorded_at="2026-08-21T00:00:00+00:00", actual=400.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 3
    assert out["span_days"] == 20.0
    assert out["confidence"] == "MEDIUM"


def test_revenue_forecast_low_confidence_with_two_points() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=100.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=400.0),
    ]
    out = _call_forecast(rows, predicted=1000.0)
    assert out["sample_count"] == 2
    assert out["confidence"] == "LOW"


def test_revenue_forecast_clamps_negative_revenue_to_zero() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=-500.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=1000.0),
    ]
    out = _call_forecast(rows, predicted=500.0)
    assert out["sample_count"] == 2
    assert out["latest_revenue"] == 1000.0
    assert out["verdict"] == "ABOVE_TARGET"


def test_revenue_forecast_all_zero_series_is_flat_without_ceiling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.0),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.0),
    ]
    out = _call_forecast(rows, predicted=None)
    assert out["latest_revenue"] == 0.0
    assert out["trend_label"] == "FLAT"
    assert out["ceiling_revenue"] is None
    assert all(f["projected_revenue"] == 0.0 for f in out["forecasts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_revenue_forecast_schema_accepts_payload() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerRevenueForecastOut

    payload = OutcomeTrackerRevenueForecastOut(
        **{
            "project_id": 7,
            "sample_count": 2,
            "span_days": 14.0,
            "latest_revenue": 400.0,
            "predicted_revenue": 1000.0,
            "ceiling_revenue": 1020.0,
            "slope_per_day": 21.43,
            "r_squared": 1.0,
            "trend_label": "CONVERGING",
            "confidence": "LOW",
            "verdict": "BELOW_TARGET",
            "forecasts": [
                {"horizon_days": 30, "projected_revenue": 1042.9}
            ],
            "days_to_target": 28.0,
            "narrative": "test",
            "key_signals": [{"label": "trend", "value": "CONVERGING"}],
        }
    )
    assert payload.project_id == 7
    assert payload.forecasts[0].horizon_days == 30
    assert payload.key_signals[0]["label"] == "trend"


def test_revenue_forecast_schema_defaults_to_insufficient() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerRevenueForecastOut

    payload = OutcomeTrackerRevenueForecastOut(project_id=7)
    assert payload.verdict == "INSUFFICIENT_DATA"
    assert payload.forecasts == []
    assert payload.key_signals == []


# ---------------------------------------------------------------------------
# Route smoke tests (fake session, no DB)
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, user_id: int = 42) -> None:
        self.id = 7
        self.user_id = user_id


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 12,
        results: dict | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 7
        self.status = "COMPLETED"
        self.results_json = results if results is not None else {
            "mean_conversion_rate": 0.05,
            "mean_revenue": 1000.0,
        }


class _FakeQuery:
    def __init__(
        self,
        items: list | None = None,
        *,
        first_result: Any = None,
    ) -> None:
        self.items = items if items is not None else []
        self._first = first_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self._first is not None:
            return self._first
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        *,
        project: _FakeProject | None = None,
        project_items: list | None = None,
        sim: _FakeSimulation | None = None,
        sim_items: list | None = None,
        rows: list | None = None,
    ) -> None:
        self.project = project if project is not None else _FakeProject()
        self.project_items = project_items
        self.sim = sim if sim is not None else _FakeSimulation()
        self.sim_items = sim_items
        self.rows = rows if rows is not None else []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self.project_items is not None:
                return _FakeQuery(self.project_items)
            return _FakeQuery([self.project])
        if name == "Simulation":
            if self.sim_items is not None:
                return _FakeQuery(self.sim_items)
            return _FakeQuery([self.sim])
        if name == "OutcomeTracker":
            return _FakeQuery(self.rows)
        return _FakeQuery([])


def _make_tracker_row(
    rid: int,
    *,
    actual: float,
    recorded_at: datetime | None = None,
    predicted: float | None = None,
) -> Any:
    from app.models.outcome_tracker import OutcomeTracker

    return OutcomeTracker(
        id=rid,
        project_id=7,
        simulation_id=12,
        actual_conversion_rate=None,
        actual_revenue=actual,
        predicted_conversion_rate=None,
        predicted_revenue=predicted,
        variance=None,
        notes=None,
        recorded_at=recorded_at
        or datetime(2026, 8, 1 + (rid - 1) * 14, tzinfo=UTC),
    )


def _call_get(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_revenue_forecast(
        project_id=7,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_route_returns_revenue_forecast_with_sim_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=100.0),
            _make_tracker_row(2, actual=150.0),
        ],
        sim=_FakeSimulation(results={"mean_revenue": 1000.0}),
    )
    out = _call_get(session=session)
    assert out.project_id == 7
    assert out.sample_count == 2
    assert out.predicted_revenue == 1000.0
    assert len(out.forecasts) == 3
    assert out.verdict == "BELOW_TARGET"


def test_route_falls_back_to_row_prediction_when_no_simulation() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=100.0, predicted=1000.0),
            _make_tracker_row(2, actual=150.0, predicted=1000.0),
        ],
        sim_items=[],
    )
    out = _call_get(session=session)
    assert out.predicted_revenue == 1000.0
    assert out.verdict == "BELOW_TARGET"


def test_route_falls_back_when_sim_results_have_no_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=100.0, predicted=1000.0),
            _make_tracker_row(2, actual=150.0, predicted=1000.0),
        ],
        sim=_FakeSimulation(results={}),
    )
    out = _call_get(session=session)
    assert out.predicted_revenue == 1000.0
    assert out.verdict == "BELOW_TARGET"


def test_route_falls_back_when_sim_prediction_is_zero() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=100.0, predicted=1000.0),
            _make_tracker_row(2, actual=150.0, predicted=1000.0),
        ],
        sim=_FakeSimulation(results={"mean_revenue": 0.0}),
    )
    out = _call_get(session=session)
    assert out.predicted_revenue == 1000.0


def test_route_falls_back_when_sim_results_are_missing() -> None:
    sim = _FakeSimulation()
    sim.results_json = None
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=100.0, predicted=1000.0),
            _make_tracker_row(2, actual=150.0, predicted=1000.0),
        ],
        sim=sim,
    )
    out = _call_get(session=session)
    assert out.predicted_revenue == 1000.0


def test_route_empty_tracker_is_insufficient() -> None:
    session = _FakeSession(rows=[])
    out = _call_get(session=session)
    assert out.sample_count == 0
    assert out.verdict == "INSUFFICIENT_DATA"


def test_route_requires_project_ownership() -> None:
    session = _FakeSession(project_items=[])
    with pytest.raises(HTTPException) as exc:
        _call_get(session=session, user_id=42)
    assert exc.value.status_code == 404


def test_route_requires_no_math_errors_on_extreme_inputs() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.0),
            _make_tracker_row(2, actual=1e9),
        ],
        sim=_FakeSimulation(results={"mean_revenue": 1000.0}),
    )
    out = _call_get(session=session)
    assert math.isfinite(out.slope_per_day or 0.0)
    assert out.verdict == "ABOVE_TARGET"

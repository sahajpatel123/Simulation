"""Tests for the post-launch conversion trajectory forecast feature."""
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
    actual: float,
) -> dict[str, Any]:
    return {
        "id": rid,
        "project_id": 7,
        "simulation_id": 12,
        "recorded_at": recorded_at,
        "actual_conversion_rate": actual,
        "actual_revenue": None,
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
    from app.simulation.outcome_tracker_forecast import (
        build_outcome_tracker_forecast,
    )

    return build_outcome_tracker_forecast(
        rows,
        project_id=project_id,
        predicted_conversion_rate=predicted,
    )


# ---------------------------------------------------------------------------
# Pure helper — insufficient data
# ---------------------------------------------------------------------------


def test_forecast_empty_rows_is_insufficient() -> None:
    out = _call_forecast(None, predicted=0.05)
    assert out["project_id"] == 7
    assert out["sample_count"] == 0
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["trend_label"] == "INSUFFICIENT_DATA"
    assert out["confidence"] == "INSUFFICIENT_DATA"
    assert out["forecasts"] == []
    assert out["days_to_target"] is None


def test_forecast_single_point_is_insufficient() -> None:
    rows = [_row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03)]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 1
    assert out["latest_actual"] == 0.03
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["forecasts"] == []


def test_forecast_skips_malformed_rows() -> None:
    rows = [
        {"id": 1, "recorded_at": None, "actual_conversion_rate": 0.03},
        {
            "id": 2,
            "recorded_at": "not-a-timestamp",
            "actual_conversion_rate": 0.04,
        },
        {
            "id": 3,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": "bad",
        },
        {
            "id": 4,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": float("nan"),
        },
        {
            "id": 5,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": True,
        },
        _row(6, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(7, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 2
    assert out["span_days"] == 14.0
    assert out["latest_actual"] == 0.04


def test_forecast_sorts_out_of_order_rows() -> None:
    rows = [
        _row(1, recorded_at="2026-08-20T00:00:00+00:00", actual=0.05),
        _row(2, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(3, recorded_at="2026-08-10T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 3
    assert out["span_days"] == 19.0
    assert out["latest_actual"] == 0.05
    assert out["verdict"] == "ABOVE_TARGET"


def test_forecast_deduplicates_same_timestamp_keeping_latest() -> None:
    rows = [
        {
            "id": 1,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": 0.03,
        },
        {
            "id": 2,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": 0.05,
        },
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.05),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 2
    assert out["latest_actual"] == 0.05
    assert out["verdict"] == "ABOVE_TARGET"


def test_forecast_all_points_same_day_is_insufficient() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(2, recorded_at="2026-08-01T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 1
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_forecast_parses_z_suffix_and_naive_datetimes() -> None:
    rows = [
        {
            "id": 1,
            "recorded_at": "2026-08-01T00:00:00Z",
            "actual_conversion_rate": 0.03,
        },
        {
            "id": 2,
            "recorded_at": datetime(2026, 8, 15, 0, 0),
            "actual_conversion_rate": 0.04,
        },
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 2
    assert out["span_days"] == 14.0


# ---------------------------------------------------------------------------
# Pure helper — verdicts and projections
# ---------------------------------------------------------------------------


def test_forecast_on_track_rising_trajectory() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.030),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.038),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.044),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=0.047),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["verdict"] == "ON_TRACK"
    assert out["trend_label"] == "CONVERGING"
    assert out["confidence"] == "HIGH"
    assert out["slope_per_day"] > 0.0
    assert out["r_squared"] is not None and out["r_squared"] >= 0.5
    assert [f["horizon_days"] for f in out["forecasts"]] == [30, 60, 90]
    assert all(
        f["projected_conversion_rate"] <= out["ceiling_conversion_rate"]
        for f in out["forecasts"]
    )
    assert out["days_to_target"] is not None and out["days_to_target"] > 0
    assert out["narrative"]
    assert any(s["label"] == "days_to_target" for s in out["key_signals"])


def test_forecast_latest_already_at_target_is_above() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.04),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.05),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["verdict"] == "ABOVE_TARGET"
    assert out["days_to_target"] is None


def test_forecast_steep_rise_is_capped_at_ceiling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.005),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=0.015),
    ]
    out = _call_forecast(rows, predicted=0.02)
    # The saturation ceiling (1.02x the target) prevents a steep short-term
    # slope from claiming an above-target projection.
    assert out["verdict"] == "ON_TRACK"
    assert (
        out["forecasts"][0]["projected_conversion_rate"]
        == out["ceiling_conversion_rate"]
    )


def test_forecast_shallow_rise_is_below_target() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.010),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=0.011),
        _row(3, recorded_at="2026-08-21T00:00:00+00:00", actual=0.012),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["verdict"] == "BELOW_TARGET"
    assert out["forecasts"][0]["projected_conversion_rate"] < 0.045


def test_forecast_flat_below_target_is_stalled() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.02),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["verdict"] == "STALLED"
    assert out["trend_label"] == "FLAT"
    assert out["slope_per_day"] == 0.0
    assert out["r_squared"] == 1.0
    assert out["days_to_target"] is None
    assert out["confidence"] == "LOW"


def test_forecast_flat_series_over_weeks_is_high_confidence() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.02),
        _row(2, recorded_at="2026-08-08T00:00:00+00:00", actual=0.02),
        _row(3, recorded_at="2026-08-15T00:00:00+00:00", actual=0.02),
        _row(4, recorded_at="2026-08-22T00:00:00+00:00", actual=0.02),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["r_squared"] == 1.0
    assert out["confidence"] == "HIGH"
    assert out["trend_label"] == "FLAT"
    assert out["verdict"] == "STALLED"


def test_forecast_declining_trend_narrative_says_falling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.05),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.03),
    ]
    out = _call_forecast(rows, predicted=0.2)
    assert out["verdict"] == "STALLED"
    assert out["trend_label"] == "DECLINING"
    assert "falling" in out["narrative"]
    assert "has not improved" not in out["narrative"]


def test_forecast_narrative_pluralizes_single_day() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.01),
        _row(2, recorded_at="2026-08-02T00:00:00+00:00", actual=0.03),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["days_to_target"] == 1.0
    assert "~1 day." in out["narrative"]
    assert "~1 days" not in out["narrative"]


def test_forecast_without_target_reports_trend_but_no_verdict() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=None)
    assert out["verdict"] == "INSUFFICIENT_DATA"
    assert out["trend_label"] == "CONVERGING"
    assert len(out["forecasts"]) == 3
    assert out["days_to_target"] is None
    assert out["predicted_conversion_rate"] is None


def test_forecast_zero_prediction_is_treated_as_no_target() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=0.0)
    assert out["predicted_conversion_rate"] is None
    assert out["verdict"] == "INSUFFICIENT_DATA"


def test_forecast_projections_are_capped_at_ceiling() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.001),
        _row(2, recorded_at="2026-08-02T00:00:00+00:00", actual=0.002),
    ]
    out = _call_forecast(rows, predicted=0.02)
    ceiling = out["ceiling_conversion_rate"]
    assert ceiling is not None and ceiling <= 1.0
    assert all(
        f["projected_conversion_rate"] <= ceiling for f in out["forecasts"]
    )


def test_forecast_medium_confidence_with_three_points() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.020),
        _row(2, recorded_at="2026-08-11T00:00:00+00:00", actual=0.030),
        _row(3, recorded_at="2026-08-21T00:00:00+00:00", actual=0.040),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 3
    assert out["span_days"] == 20.0
    assert out["confidence"] == "MEDIUM"


def test_forecast_low_confidence_with_two_points() -> None:
    rows = [
        _row(1, recorded_at="2026-08-01T00:00:00+00:00", actual=0.03),
        _row(2, recorded_at="2026-08-15T00:00:00+00:00", actual=0.04),
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 2
    assert out["confidence"] == "LOW"


def test_forecast_clamps_out_of_range_rates() -> None:
    rows = [
        {
            "id": 1,
            "recorded_at": "2026-08-01T00:00:00+00:00",
            "actual_conversion_rate": -0.5,
        },
        {
            "id": 2,
            "recorded_at": "2026-08-15T00:00:00+00:00",
            "actual_conversion_rate": 1.5,
        },
    ]
    out = _call_forecast(rows, predicted=0.05)
    assert out["sample_count"] == 2
    assert out["latest_actual"] == 1.0
    assert out["verdict"] == "ABOVE_TARGET"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_forecast_schema_accepts_payload() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerForecastOut

    payload = OutcomeTrackerForecastOut(
        **{
            "project_id": 7,
            "sample_count": 2,
            "span_days": 14.0,
            "latest_actual": 0.04,
            "predicted_conversion_rate": 0.05,
            "ceiling_conversion_rate": 0.051,
            "slope_per_day": 0.0007,
            "r_squared": 1.0,
            "trend_label": "CONVERGING",
            "confidence": "LOW",
            "verdict": "BELOW_TARGET",
            "forecasts": [
                {"horizon_days": 30, "projected_conversion_rate": 0.061}
            ],
            "days_to_target": 14.3,
            "narrative": "test",
            "key_signals": [{"label": "trend", "value": "CONVERGING"}],
        }
    )
    assert payload.project_id == 7
    assert payload.forecasts[0].horizon_days == 30
    assert payload.key_signals[0]["label"] == "trend"


def test_forecast_schema_defaults_to_insufficient() -> None:
    from app.schemas.outcome_tracker import OutcomeTrackerForecastOut

    payload = OutcomeTrackerForecastOut(project_id=7)
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
        actual_conversion_rate=actual,
        actual_revenue=100.0,
        predicted_conversion_rate=predicted,
        predicted_revenue=1000.0,
        variance=None,
        notes=None,
        recorded_at=recorded_at
        or datetime(2026, 8, rid, tzinfo=UTC),
    )


def _call_get(
    *,
    session: _FakeSession | None = None,
    user_id: int = 42,
) -> Any:
    from app.api.v1 import outcomes as mod

    return mod.get_outcome_tracker_forecast(
        project_id=7,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": user_id})(),
    )


def test_route_returns_forecast_with_sim_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.03),
            _make_tracker_row(2, actual=0.04),
        ],
        sim=_FakeSimulation(results={"mean_conversion_rate": 0.05}),
    )
    out = _call_get(session=session)
    assert out.project_id == 7
    assert out.sample_count == 2
    assert out.predicted_conversion_rate == 0.05
    assert len(out.forecasts) == 3
    assert out.verdict in ("BELOW_TARGET", "ON_TRACK", "ABOVE_TARGET")


def test_route_falls_back_to_row_prediction_when_no_simulation() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.03, predicted=0.05),
            _make_tracker_row(2, actual=0.04, predicted=0.05),
        ],
        sim_items=[],
    )
    out = _call_get(session=session)
    assert out.predicted_conversion_rate == 0.05
    assert out.verdict in ("ON_TRACK", "ABOVE_TARGET")


def test_route_falls_back_when_sim_results_have_no_prediction() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.03, predicted=0.05),
            _make_tracker_row(2, actual=0.04, predicted=0.05),
        ],
        sim=_FakeSimulation(results={}),
    )
    out = _call_get(session=session)
    assert out.predicted_conversion_rate == 0.05
    assert out.verdict in ("ON_TRACK", "ABOVE_TARGET")


def test_route_falls_back_when_sim_prediction_is_zero() -> None:
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.03, predicted=0.05),
            _make_tracker_row(2, actual=0.04, predicted=0.05),
        ],
        sim=_FakeSimulation(results={"mean_conversion_rate": 0.0}),
    )
    out = _call_get(session=session)
    assert out.predicted_conversion_rate == 0.05


def test_route_falls_back_when_sim_results_are_missing() -> None:
    sim = _FakeSimulation()
    sim.results_json = None
    session = _FakeSession(
        rows=[
            _make_tracker_row(1, actual=0.03, predicted=0.05),
            _make_tracker_row(2, actual=0.04, predicted=0.05),
        ],
        sim=sim,
    )
    out = _call_get(session=session)
    assert out.predicted_conversion_rate == 0.05


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
            _make_tracker_row(2, actual=1.0),
        ],
        sim=_FakeSimulation(results={"mean_conversion_rate": 0.05}),
    )
    out = _call_get(session=session)
    assert math.isfinite(out.slope_per_day or 0.0)
    assert out.verdict == "ABOVE_TARGET"

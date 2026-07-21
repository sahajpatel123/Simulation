"""
Tests for simulation-trend helpers and the
``GET /projects/{id}/simulation-trend`` endpoint smoke-check
(cycle 36 simulation-trend-analytics).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _row(
    sim_id: int,
    status: str,
    cr: float,
    signal: float | None = 0.7,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": sim_id,
        "status": status,
        "signal_quality": signal,
        "results_json": {
            "population_weighted_conversion": cr,
            "conversion_rate": cr,
        },
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# build_simulation_trend
# ---------------------------------------------------------------------------


def test_empty_input_yields_zero_state() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    out = build_simulation_trend(None, project_id=1)
    assert out["project_id"] == 1
    assert out["total_runs"] == 0
    assert out["completed_runs"] == 0
    assert out["status_breakdown"] == {}
    assert out["history"] == []
    assert out["best_run"] is None
    assert out["worst_run"] is None
    assert out["latest_run"] is None
    assert out["trend_slope"] is None
    assert out["stability_score"] is None
    assert out["conversion_stats"]["count"] == 0


def test_status_breakdown_counts_correctly() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        _row(1, "COMPLETED", 0.05),
        _row(2, "COMPLETED", 0.06),
        _row(3, "RUNNING", 0.0),
        _row(4, "FAILED", 0.0),
        _row(5, "QUEUED", 0.0),
    ]
    out = build_simulation_trend(rows, project_id=1)
    assert out["status_breakdown"] == {
        "COMPLETED": 2,
        "RUNNING": 1,
        "FAILED": 1,
        "QUEUED": 1,
    }


def test_history_carries_delta_and_direction() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        _row(1, "COMPLETED", 0.05),
        _row(2, "COMPLETED", 0.08),  # delta +0.03 UP
        _row(3, "COMPLETED", 0.06),  # delta -0.02 DOWN
        _row(4, "COMPLETED", 0.06),  # delta 0 FLAT
    ]
    out = build_simulation_trend(rows, project_id=1)
    history = out["history"]
    assert history[0].delta_from_prev is None
    assert history[0].direction is None
    assert history[1].delta_from_prev == 0.03
    assert history[1].direction == "UP"
    assert history[2].delta_from_prev == -0.02
    assert history[2].direction == "DOWN"
    assert history[3].delta_from_prev == 0.0
    assert history[3].direction == "FLAT"


def test_best_worst_latest_runs_picked_from_completed_only() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        _row(1, "COMPLETED", 0.05),
        _row(2, "FAILED", 0.99),  # ignored
        _row(3, "COMPLETED", 0.10),
        _row(4, "COMPLETED", 0.03),
        _row(5, "COMPLETED", 0.07),
    ]
    out = build_simulation_trend(rows, project_id=1)
    assert out["best_run"].simulation_id == 3
    assert out["worst_run"].simulation_id == 4
    assert out["latest_run"].simulation_id == 5


def test_conversion_stats_min_max_mean_median() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", cr) for i, cr in enumerate([0.04, 0.06, 0.10])]
    out = build_simulation_trend(rows, project_id=1)
    stats = out["conversion_stats"]
    assert stats["count"] == 3
    assert stats["min"] == 0.04
    assert stats["max"] == 0.10
    assert stats["mean"] == pytest_float((0.04 + 0.06 + 0.10) / 3)
    assert stats["median"] == 0.06
    assert stats["std"] is not None and stats["std"] > 0


def test_conversion_stats_median_handles_even_count() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", cr) for i, cr in enumerate([0.04, 0.06, 0.08, 0.10])]
    out = build_simulation_trend(rows, project_id=1)
    # Median = (0.06 + 0.08) / 2 = 0.07
    assert out["conversion_stats"]["median"] == 0.07


def test_conversion_stats_handles_single_value() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(1, "COMPLETED", 0.05)]
    out = build_simulation_trend(rows, project_id=1)
    stats = out["conversion_stats"]
    assert stats["count"] == 1
    assert stats["min"] == 0.05
    assert stats["max"] == 0.05
    assert stats["mean"] == 0.05
    assert stats["median"] == 0.05
    # std requires n > 1.
    assert stats["std"] is None
    # trend + stability need 2+ points.
    assert out["trend_slope"] is None
    assert out["stability_score"] is None


def test_conversion_stats_handles_all_zero_rates() -> None:
    """If every completed run has conversion_rate = 0, mean = 0 and stability
    must return None (we can't divide by zero)."""
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", 0.0) for i in range(3)]
    out = build_simulation_trend(rows, project_id=1)
    stats = out["conversion_stats"]
    assert stats["mean"] == 0.0
    assert stats["std"] == 0.0
    assert out["stability_score"] is None  # mean=0 → undefined


def test_trend_slope_positive_on_strictly_increasing_rates() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", cr) for i, cr in enumerate([0.01, 0.02, 0.03, 0.04])]
    out = build_simulation_trend(rows, project_id=1)
    assert out["trend_slope"] is not None
    assert out["trend_slope"] > 0


def test_trend_slope_negative_on_decreasing_rates() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", cr) for i, cr in enumerate([0.10, 0.08, 0.06])]
    out = build_simulation_trend(rows, project_id=1)
    assert out["trend_slope"] < 0


def test_trend_slope_zero_on_constant_rates() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", 0.05) for i in range(3)]
    out = build_simulation_trend(rows, project_id=1)
    assert out["trend_slope"] == 0.0


def test_stability_score_perfect_for_identical_rates() -> None:
    """When std=0, cv=0, score=1/(1+0)=1."""
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", 0.05) for i in range(4)]
    out = build_simulation_trend(rows, project_id=1)
    assert out["stability_score"] == 1.0


def test_stability_score_bounded_in_unit_interval() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(i, "COMPLETED", cr) for i, cr in enumerate([0.01, 0.05, 0.10])]
    out = build_simulation_trend(rows, project_id=1)
    assert 0.0 <= out["stability_score"] <= 1.0


def test_results_json_string_input_handled() -> None:
    """Some persistence layers may serialise JSONB to strings — the helper
    must coerce them back to a dict before reading keys."""
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        {
            "id": 1,
            "status": "COMPLETED",
            "signal_quality": 0.5,
            "results_json": json.dumps({"population_weighted_conversion": 0.07}),
            "created_at": None,
        }
    ]
    out = build_simulation_trend(rows, project_id=1)
    # The JSON string is parsed; the conversion rate shows up in history
    # and in best_run.
    assert out["history"][0].conversion_rate == 0.07
    assert out["best_run"] is not None
    assert out["best_run"].conversion_rate == 0.07


def test_results_json_garbage_string_falls_back_to_zero() -> None:
    """Unparseable JSON strings degrade to an empty results dict, which
    surfaces as cr=0 — not an exception."""
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        {
            "id": 1,
            "status": "COMPLETED",
            "signal_quality": 0.5,
            "results_json": "{not valid json",
            "created_at": None,
        }
    ]
    out = build_simulation_trend(rows, project_id=1)
    assert out["history"][0].conversion_rate == 0.0


def test_history_preserves_input_order() -> None:
    """Caller sorts ascending; helper must preserve the input ordering."""
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [
        _row(7, "COMPLETED", 0.07, created_at="2026-07-01T00:00:00"),
        _row(2, "COMPLETED", 0.02, created_at="2026-06-01T00:00:00"),
        _row(5, "COMPLETED", 0.05, created_at="2026-05-01T00:00:00"),
    ]
    out = build_simulation_trend(rows, project_id=1)
    ids = [r.simulation_id for r in out["history"]]
    assert ids == [7, 2, 5]


def test_datetime_input_serialised_to_isoformat() -> None:
    from app.simulation.simulation_trend import build_simulation_trend

    rows = [_row(1, "COMPLETED", 0.05, created_at=datetime(2026, 1, 1, 12))]
    out = build_simulation_trend(rows, project_id=1)
    assert out["history"][0].created_at == "2026-01-01T12:00:00"
    assert out["best_run"].created_at == "2026-01-01T12:00:00"


# ---------------------------------------------------------------------------
# Pydantic schema round-trip
# ---------------------------------------------------------------------------


def test_simulation_trend_out_round_trip() -> None:
    from app.schemas.simulation_trend import (
        RunDetail,
        RunSummary,
        SimulationTrendOut,
    )

    out = SimulationTrendOut(
        project_id=1,
        total_runs=3,
        completed_runs=2,
        status_breakdown={"COMPLETED": 2, "FAILED": 1},
        history=[
            RunSummary(
                simulation_id=1,
                status="COMPLETED",
                signal_quality=0.5,
                conversion_rate=0.05,
                delta_from_prev=None,
                direction=None,
                created_at="2026-01-01T00:00:00",
            )
        ],
        best_run=RunDetail(
            simulation_id=1,
            conversion_rate=0.05,
            signal_quality=0.5,
            created_at="2026-01-01T00:00:00",
            status="COMPLETED",
        ),
        worst_run=RunDetail(
            simulation_id=2,
            conversion_rate=0.02,
            signal_quality=0.4,
            created_at="2026-02-01T00:00:00",
            status="COMPLETED",
        ),
        latest_run=RunDetail(
            simulation_id=3,
            conversion_rate=0.04,
            signal_quality=0.6,
            created_at="2026-03-01T00:00:00",
            status="FAILED",
        ),
        conversion_stats={
            "count": 2,
            "min": 0.02,
            "max": 0.05,
            "mean": 0.035,
            "median": 0.035,
            "std": 0.015,
        },
        trend_slope=0.01,
        stability_score=0.85,
        generated_at="2026-07-21T20:00:00+00:00",
    )
    dumped = out.model_dump()
    assert dumped["project_id"] == 1
    assert dumped["best_run"]["simulation_id"] == 1
    assert dumped["trend_slope"] == 0.01
    json.dumps(dumped)


def test_simulation_trend_out_defaults_when_empty() -> None:
    from app.schemas.simulation_trend import SimulationTrendOut

    out = SimulationTrendOut(project_id=1)
    assert out.total_runs == 0
    assert out.completed_runs == 0
    assert out.history == []
    assert out.best_run is None
    assert out.worst_run is None
    assert out.latest_run is None
    assert out.trend_slope is None
    assert out.stability_score is None


# ---------------------------------------------------------------------------
# Route registration smoke-check
# ---------------------------------------------------------------------------


def test_projects_router_exposes_simulation_trend_endpoint() -> None:
    src_path = "backend/app/api/v1/projects.py"
    with open(src_path) as fh:
        source = fh.read()
    assert '"/{project_id}/simulation-trend"' in source
    assert "def get_simulation_trend(" in source
    assert "response_model=SimulationTrendOut" in source
    assert "_build_simulation_trend" in source


def test_simulation_trend_helper_is_pure() -> None:
    import inspect

    from app.simulation import simulation_trend

    source = inspect.getsource(simulation_trend)
    forbidden = ("sqlalchemy", "SessionLocal", "get_db")
    for token in forbidden:
        assert token.lower() not in source.lower(), (
            f"simulation_trend.py must not depend on {token}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pytest_float(value: float, tol: float = 1e-6) -> float:
    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and abs(float(other) - value) < tol

        def __repr__(self) -> str:
            return f"≈{value}"

    return _Approx()  # type: ignore[return-value]

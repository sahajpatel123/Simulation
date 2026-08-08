"""
Tests for the journey-trend module and its Pydantic schema contract.

Covers point ordering / deltas, purchase statistics, best/worst selection,
trend slope and stability, momentum, malformed-row resilience, anchor
percentile ranking, insight generation, and the endpoint response model.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.schemas.journey_trend import JourneyTrendOut
from app.simulation.journey_analytics import summarise_journey_matrices
from app.simulation.journey_benchmark import LEAK_STAGE_ORDER
from app.simulation.journey_trend import build_journey_trend


def _results() -> dict:
    return {
        "cluster_weights": {"c0": 0.6, "c1": 0.4},
        "per_cluster_matrices": {
            "c0": {
                "ARRIVE->BROWSE": 0.95,
                "BROWSE->CONSIDER": 0.80,
                "CONSIDER->DECIDE": 0.70,
                "DECIDE->PURCHASE": 0.50,
            },
            "c1": {},
        },
    }


def _strong_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.95
    return results


def _super_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.99
    return results


def _weak_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.10
    return results


def _summary(results: dict) -> dict:
    built = summarise_journey_matrices(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )
    assert built is not None
    return built


def _row(
    sim_id: int,
    results: dict,
    *,
    project_id: int = 10,
    created_at: str | None = None,
) -> dict:
    return {
        "simulation_id": sim_id,
        "project_id": project_id,
        "created_at": created_at,
        "journey_summary": _summary(results),
    }


def _improving_rows() -> list[dict]:
    return [
        _row(1, _weak_results(), created_at="2026-01-01T00:00:00Z"),
        _row(2, _results(), created_at="2026-02-01T00:00:00Z"),
        _row(3, _strong_results(), created_at="2026-03-01T00:00:00Z"),
    ]


def _payload(rows: list[dict] | None, anchor_id: int = 3) -> dict:
    return build_journey_trend(
        rows,
        anchor_simulation_id=anchor_id,
        project_id=10,
    )


def test_trend_orders_points_and_computes_deltas() -> None:
    payload = _payload(_improving_rows(), anchor_id=3)

    assert [p["simulation_id"] for p in payload["points"]] == [1, 2, 3]
    assert payload["points"][0]["direction"] is None
    assert payload["points"][0]["delta_from_prev"] is None
    assert payload["points"][1]["direction"] == "UP"
    assert payload["points"][1]["delta_from_prev"] > 0.0
    assert payload["points"][2]["direction"] == "UP"
    assert payload["points"][2]["delta_from_prev"] > 0.0
    assert [p["is_anchor"] for p in payload["points"]] == [False, False, True]
    assert payload["points"][2]["created_at"] == "2026-03-01T00:00:00Z"


def test_trend_computes_stats_best_worst_slope_and_stability() -> None:
    payload = _payload(_improving_rows(), anchor_id=2)
    stats = payload["summary"]["purchase_stats"]

    assert stats["count"] == 3.0
    assert stats["min"] < stats["max"]
    assert stats["mean"] == pytest.approx(
        sum(
            p["purchase_probability"]
            for p in payload["points"]
        )
        / 3.0
    )
    assert stats["std"] is not None and stats["std"] >= 0.0
    assert payload["summary"]["best_point"]["simulation_id"] == 3
    assert payload["summary"]["worst_point"]["simulation_id"] == 1
    assert payload["summary"]["trend_slope"] > 0.0
    assert payload["summary"]["stability_score"] is not None
    assert 0.0 <= payload["summary"]["stability_score"] <= 1.0


def test_trend_momentum_counts_recent_transitions() -> None:
    rows = [
        _row(1, _weak_results()),
        _row(2, _results()),
        _row(3, _strong_results()),
        _row(4, _super_results()),
    ]
    payload = _payload(rows, anchor_id=4)
    momentum = payload["summary"]["momentum"]

    assert momentum["improved_count"] == 3
    assert momentum["declined_count"] == 0
    assert momentum["flat_count"] == 0
    assert momentum["improvement_share_pct"] == 100.0
    assert momentum["latest_delta"] > 0.0


def test_trend_skips_malformed_rows() -> None:
    rows = _improving_rows() + [
        {"simulation_id": "junk", "journey_summary": None},
        {
            "simulation_id": 99,
            "journey_summary": {
                "purchase_probability": float("nan"),
                "abandon_probability": 0.9,
                "expected_steps_to_absorb": 2.0,
                "expected_revisits": 0.0,
            },
        },
        {
            "simulation_id": 98,
            "journey_summary": {
                "purchase_probability": 0.5,
                "abandon_probability": 1.2,
                "expected_steps_to_absorb": 2.0,
                "expected_revisits": 0.0,
            },
        },
        "junk-row",
    ]
    payload = _payload(rows, anchor_id=3)

    assert payload["summary"]["raw_count"] == 7
    assert payload["summary"]["included_count"] == 3
    assert payload["summary"]["skipped_count"] == 4
    assert [p["simulation_id"] for p in payload["points"]] == [1, 2, 3]


def test_trend_handles_single_point() -> None:
    payload = _payload([_row(7, _results())], anchor_id=7)

    assert payload["summary"]["included_count"] == 1
    assert payload["summary"]["trend_slope"] is None
    assert payload["summary"]["stability_score"] is None
    assert payload["summary"]["momentum"]["latest_delta"] is None
    assert payload["anchor_percentile_rank"] is None
    assert len(payload["insights"]) == 1
    assert "no direction yet" in payload["insights"][0]


def test_trend_handles_empty_rows() -> None:
    payload = _payload([], anchor_id=7)

    assert payload["summary"]["included_count"] == 0
    assert payload["summary"]["raw_count"] == 0
    assert payload["summary"]["purchase_stats"]["count"] == 0.0
    assert payload["summary"]["best_point"] is None
    assert payload["summary"]["worst_point"] is None
    assert payload["anchor_percentile_rank"] is None
    assert "No journey-capable simulations" in payload["insights"][0]


def test_trend_anchor_percentile_rank() -> None:
    rows = [_row(1, _strong_results()), _row(2, _weak_results()), _row(3, _results())]

    worst = _payload(rows, anchor_id=2)
    assert worst["anchor_percentile_rank"] == 0.0
    assert any("worse than 100%" in i for i in worst["insights"])

    best = _payload(rows, anchor_id=1)
    assert best["anchor_percentile_rank"] == 100.0
    assert any("better than 100%" in i for i in best["insights"])


def test_trend_modal_exit_and_stage_leak_medians() -> None:
    payload = _payload(_improving_rows(), anchor_id=3)

    assert payload["summary"]["most_common_primary_exit_stage"] == "BROWSE"
    assert set(payload["summary"]["stage_leak_medians"]) == set(LEAK_STAGE_ORDER)
    assert all(v >= 0.0 for v in payload["summary"]["stage_leak_medians"].values())
    assert payload["summary"]["latest_stage_leaks"] == (
        payload["points"][-1]["exit_stage_distribution"]
    )


def test_trend_insights_cover_direction_and_rank() -> None:
    payload = _payload(_improving_rows(), anchor_id=3)
    joined = "\n".join(payload["insights"])

    assert "above your median" in joined
    assert "improved by +" in joined
    assert "trending up" in joined
    assert "converts better than" in joined


def test_trend_schema_contract() -> None:
    payload = _payload(_improving_rows(), anchor_id=3)
    payload["generated_at"] = datetime.now(tz=UTC).isoformat()

    out = JourneyTrendOut(**payload)
    assert out.simulation_id == 3
    assert out.project_id == 10
    assert out.status == "COMPLETED"
    assert len(out.points) == 3
    assert out.points[2].is_anchor is True
    assert out.summary.included_count == 3
    assert out.summary.best_point is not None
    assert out.summary.worst_point is not None
    assert out.anchor_percentile_rank == 100.0
    assert out.insights
    assert out.generated_at

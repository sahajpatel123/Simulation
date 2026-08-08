"""
Tests for the journey-benchmark module and its Pydantic schema contract.

Covers the lightweight funnel summariser, cohort distribution statistics,
percentile ranking, malformed-input resilience, insight generation, and the
endpoint response model.
"""
from __future__ import annotations

import math

import pytest

from app.schemas.journey_benchmark import JourneyBenchmarkOut
from app.simulation.journey_analytics import (
    build_journey_analytics,
    summarise_journey_matrices,
)
from app.simulation.journey_benchmark import (
    LEAK_STAGE_ORDER,
    build_journey_benchmark,
)


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
    return {
        "cluster_weights": {"c0": 0.6, "c1": 0.4},
        "per_cluster_matrices": {
            "c0": {
                "ARRIVE->BROWSE": 0.95,
                "BROWSE->CONSIDER": 0.80,
                "CONSIDER->DECIDE": 0.70,
                "DECIDE->PURCHASE": 0.95,
            },
            "c1": {},
        },
    }


def _weak_results() -> dict:
    return {
        "cluster_weights": {"c0": 0.6, "c1": 0.4},
        "per_cluster_matrices": {
            "c0": {
                "ARRIVE->BROWSE": 0.95,
                "BROWSE->CONSIDER": 0.80,
                "CONSIDER->DECIDE": 0.70,
                "DECIDE->PURCHASE": 0.10,
            },
            "c1": {},
        },
    }


def _current_payload() -> dict:
    results = _results()
    return build_journey_analytics(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )


def _strong_payload() -> dict:
    results = _strong_results()
    return build_journey_analytics(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )


def _weak_payload() -> dict:
    results = _weak_results()
    return build_journey_analytics(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )


def _cohort() -> list[dict]:
    return [
        summarise_journey_matrices(
            _strong_results()["per_cluster_matrices"],
            _strong_results()["cluster_weights"],
        ),
        summarise_journey_matrices(
            _weak_results()["per_cluster_matrices"],
            _weak_results()["cluster_weights"],
        ),
    ]


# ---------------------------------------------------------------------------
# Lightweight summariser
# ---------------------------------------------------------------------------


def test_summariser_matches_full_journey_analytics_headline() -> None:
    results = _results()
    summary = summarise_journey_matrices(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )
    full = build_journey_analytics(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )

    assert summary is not None
    assert summary["purchase_probability"] == pytest.approx(
        full["purchase_probability"]
    )
    assert summary["abandon_probability"] == pytest.approx(
        full["abandon_probability"]
    )
    assert summary["expected_steps_to_absorb"] == pytest.approx(
        full["expected_steps_to_absorb"]
    )
    assert summary["expected_revisits"] == pytest.approx(full["expected_revisits"])
    assert summary["exit_stage_distribution"] == pytest.approx(
        full["exit_stage_distribution"]
    )
    assert summary["primary_exit_stage"] == "BROWSE"


def test_summariser_returns_none_without_usable_matrices() -> None:
    assert summarise_journey_matrices(None) is None
    assert summarise_journey_matrices({}) is None
    assert summarise_journey_matrices("junk") is None
    assert summarise_journey_matrices({"c0": "junk"}) is None


def test_summariser_survives_malformed_weights() -> None:
    results = _results()
    results["cluster_weights"] = {
        "c0": float("inf"),
        "c1": float("nan"),
        "c2": -1.0,
    }
    summary = summarise_journey_matrices(
        results["per_cluster_matrices"],
        results["cluster_weights"],
    )

    assert summary is not None
    assert math.isfinite(summary["purchase_probability"])
    assert 0.0 <= summary["purchase_probability"] <= 1.0
    assert sum(summary["exit_stage_distribution"].values()) == pytest.approx(
        summary["abandon_probability"],
        abs=1e-5,
    )


# ---------------------------------------------------------------------------
# Benchmark composition
# ---------------------------------------------------------------------------


def test_empty_cohort_returns_empty_benchmark() -> None:
    payload = build_journey_benchmark(_current_payload(), [])

    assert payload["cohort_size"] == 0
    assert payload["percentile_rank"] is None
    assert payload["distribution"]["median_purchase_probability"] is None
    assert payload["distribution"]["stage_leak_medians"] == {}
    assert payload["insights"]
    assert "No previous journey-capable simulations" in payload["insights"][0]
    assert payload["meta"]["skipped_invalid_summaries"] == 0


def test_benchmark_percentile_rank_and_distribution() -> None:
    current = _current_payload()
    cohort = _cohort()
    payload = build_journey_benchmark(current, cohort)

    assert payload["cohort_size"] == 2
    assert payload["percentile_rank"] == pytest.approx(50.0)
    assert payload["current"]["purchase_probability"] == pytest.approx(0.060933)

    distribution = payload["distribution"]
    assert distribution["min_purchase_probability"] < current["purchase_probability"]
    assert distribution["max_purchase_probability"] > current["purchase_probability"]
    assert distribution["p25_purchase_probability"] == pytest.approx(
        distribution["min_purchase_probability"]
    )
    assert distribution["p75_purchase_probability"] == pytest.approx(
        distribution["max_purchase_probability"]
    )
    assert distribution["median_purchase_probability"] == pytest.approx(
        distribution["mean_purchase_probability"]
    )
    assert distribution["most_common_primary_exit_stage"] == "BROWSE"
    assert set(distribution["stage_leak_medians"]) == set(LEAK_STAGE_ORDER)
    assert all(v >= 0.0 for v in distribution["stage_leak_medians"].values())

    assert any("Ranks above 50.0%" in i for i in payload["insights"])
    assert any("above" in i and "median idea" in i for i in payload["insights"])


def test_benchmark_ties_count_as_below() -> None:
    current = _current_payload()
    cohort = [
        summarise_journey_matrices(
            _results()["per_cluster_matrices"],
            _results()["cluster_weights"],
        ),
        summarise_journey_matrices(
            _weak_results()["per_cluster_matrices"],
            _weak_results()["cluster_weights"],
        ),
    ]
    payload = build_journey_benchmark(current, cohort)

    # One of two cohort sims converts strictly below the current one.
    assert payload["percentile_rank"] == pytest.approx(50.0)


def test_benchmark_skips_invalid_cohort_entries() -> None:
    cohort = _cohort() + [
        None,
        "junk",
        {},
        {"purchase_probability": float("nan")},
        {"purchase_probability": -0.5},
        {"purchase_probability": 2.0},
    ]
    payload = build_journey_benchmark(_current_payload(), cohort)

    assert payload["cohort_size"] == 2
    assert payload["meta"]["skipped_invalid_summaries"] == 6
    assert payload["percentile_rank"] == pytest.approx(50.0)


def test_benchmark_skips_cohort_entries_with_out_of_range_metrics() -> None:
    cohort = _cohort() + [
        {
            "purchase_probability": 0.5,
            "abandon_probability": 1.2,
            "expected_steps_to_absorb": 2.0,
            "expected_revisits": 0.0,
            "exit_stage_distribution": {"BROWSE": 0.4},
        },
        {
            "purchase_probability": 0.5,
            "abandon_probability": 0.5,
            "expected_steps_to_absorb": -1.0,
            "expected_revisits": 0.0,
            "exit_stage_distribution": {"BROWSE": 0.4},
        },
        {
            "purchase_probability": 0.5,
            "abandon_probability": 0.5,
            "expected_steps_to_absorb": 2.0,
            "expected_revisits": float("-inf"),
            "exit_stage_distribution": {"BROWSE": 0.4},
        },
        {"purchase_probability": 0.5},  # missing every other metric
    ]
    payload = build_journey_benchmark(_current_payload(), cohort)

    assert payload["cohort_size"] == 2
    assert payload["meta"]["skipped_invalid_summaries"] == 4
    assert payload["percentile_rank"] == pytest.approx(50.0)


def test_benchmark_ignores_unknown_exit_stages() -> None:
    cohort = [
        {
            "purchase_probability": 0.3,
            "abandon_probability": 0.7,
            "expected_steps_to_absorb": 2.0,
            "expected_revisits": 0.0,
            "exit_stage_distribution": {"NOT_A_STAGE": 1.0, "BROWSE": 0.4},
        }
    ]
    payload = build_journey_benchmark(_current_payload(), cohort)

    assert payload["distribution"]["most_common_primary_exit_stage"] == "BROWSE"
    assert payload["distribution"]["stage_leak_medians"] == {
        "ARRIVE": 0.0,
        "BROWSE": 0.4,
        "CONSIDER": 0.0,
        "DECIDE": 0.0,
    }
    assert "NOT_A_STAGE" not in payload["distribution"]["stage_leak_medians"]
    assert "NOT_A_STAGE" not in " ".join(payload["insights"])


def test_current_payload_with_missing_keys_defaults_safely() -> None:
    payload = build_journey_benchmark({}, [])

    assert payload["cohort_size"] == 0
    assert payload["current"]["purchase_probability"] == 0.0
    assert payload["current"]["primary_exit_stage"] is None
    assert payload["current"]["exit_stage_distribution"] == {}


def test_current_payload_out_of_range_values_are_clamped() -> None:
    payload = build_journey_benchmark(
        {
            "purchase_probability": 1.5,
            "abandon_probability": -0.4,
            "expected_steps_to_absorb": -3.0,
            "expected_revisits": float("nan"),
            "exit_stage_distribution": {"BROWSE": float("inf")},
        },
        [],
    )

    current = payload["current"]
    assert current["purchase_probability"] == 1.0
    assert current["abandon_probability"] == 0.0
    assert current["expected_steps_to_absorb"] == 0.0
    assert current["expected_revisits"] == 0.0
    assert current["exit_stage_distribution"] == {}
    assert current["primary_exit_stage"] is None
    # The clamped payload must satisfy the Pydantic response contract.
    JourneyBenchmarkOut(simulation_id=1, project_id=1, **payload)


def test_percentile_insights_handle_extremes() -> None:
    strong = summarise_journey_matrices(
        _strong_results()["per_cluster_matrices"],
        _strong_results()["cluster_weights"],
    )
    weak = summarise_journey_matrices(
        _weak_results()["per_cluster_matrices"],
        _weak_results()["cluster_weights"],
    )

    top = build_journey_benchmark(_strong_payload(), [weak, weak])
    assert top["percentile_rank"] == 100.0
    assert any(
        "Outperforms every benchmarked simulation" in i
        for i in top["insights"]
    )

    bottom = build_journey_benchmark(_weak_payload(), [strong, strong])
    assert bottom["percentile_rank"] == 0.0
    assert any(
        "converts at least as well as this one" in i
        for i in bottom["insights"]
    )


def test_benchmark_payload_validates_response_schema() -> None:
    payload = build_journey_benchmark(_current_payload(), _cohort())
    out = JourneyBenchmarkOut(
        simulation_id=1,
        project_id=10,
        **payload,
    )

    assert out.cohort_size == 2
    assert out.percentile_rank == pytest.approx(50.0)
    assert out.current.purchase_probability == pytest.approx(0.060933)
    assert out.distribution.most_common_primary_exit_stage == "BROWSE"
    assert out.insights

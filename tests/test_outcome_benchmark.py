"""
Tests for the real-world outcome peer-benchmark module and its schema
contract.

Covers no-data / no-category / no-peer degradation, distribution
percentiles, fair midrank ranking for ties, verdict mapping, malformed peer
filtering, prediction-gap insights, and the small-cohort caveat.
"""
from __future__ import annotations

import math

import pytest

from app.schemas.outcome_benchmark import OutcomeBenchmarkOut
from app.simulation.outcome_benchmark import (
    MAX_PEERS,
    MIN_PEERS_FOR_SUFFICIENT_DATA,
    VERDICT_ABOVE_MEDIAN,
    VERDICT_AT_MEDIAN,
    VERDICT_BOTTOM_QUARTILE,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_TOP_QUARTILE,
    build_outcome_benchmark,
)


def test_peer_scan_bounds_are_contract_constants() -> None:
    assert MAX_PEERS == 500
    assert MIN_PEERS_FOR_SUFFICIENT_DATA == 5


def _current(
    actual: float = 0.05,
    predicted: float | None = 0.04,
) -> dict:
    return {
        "outcome_id": 1,
        "simulation_id": 7,
        "project_id": 10,
        "days_since_launch": 30,
        "actual_conversion_rate": actual,
        "predicted_conversion_rate": predicted,
        "launched": True,
        "data_confidence": "ESTIMATED",
        "created_at": "2026-08-01T00:00:00+00:00",
    }


def _peers(
    *rates: float,
    changed: list[bool] | None = None,
) -> list[dict]:
    flags = changed if changed is not None else [False] * len(rates)
    return [
        {
            "actual_conversion_rate": rate,
            "product_changed_since_sim": flag,
        }
        for rate, flag in zip(rates, flags)
    ]


def test_no_outcome_returns_no_data_payload() -> None:
    payload = build_outcome_benchmark(None, [])

    assert payload["has_data"] is False
    assert payload["current"] is None
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert payload["distribution"]["peer_count"] == 0
    assert "Record a founder outcome" in payload["insights"][0]
    assert payload["key_signals"][0]["value"] == "NO_OUTCOME"


def test_outcome_without_category_has_no_peers() -> None:
    payload = build_outcome_benchmark(_current(), [], category=None)

    assert payload["has_data"] is True
    assert payload["current"] is not None
    assert payload["category"] is None
    assert payload["distribution"]["peer_count"] == 0
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert "No product category detected" in payload["insights"][0]


def test_benchmark_ranks_outperforming_launch_top_quartile() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.06),
        _peers(0.01, 0.02, 0.03, 0.04, 0.05),
        category="saas",
    )

    assert payload["category"] == "saas"
    assert payload["distribution"]["peer_count"] == 5
    assert payload["distribution"]["median"] == pytest.approx(0.03)
    assert payload["percentile_rank"] == 100.0
    assert payload["median_comparison"] == "ABOVE"
    assert payload["verdict"] == VERDICT_TOP_QUARTILE
    assert any(
        "Outperforms every one of 5" in i for i in payload["insights"]
    )
    assert payload["meta"]["peers_usable"] == 5
    assert payload["meta"]["data_sufficient"] is True


def test_benchmark_ties_use_fair_midrank() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.05),
        _peers(0.01, 0.05, 0.05, 0.09),
        category="saas",
    )

    assert payload["percentile_rank"] == 50.0
    assert payload["median_comparison"] == "AT"
    assert payload["verdict"] == VERDICT_AT_MEDIAN


def test_benchmark_above_median_without_top_quartile() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.06),
        _peers(0.01, 0.02, 0.08, 0.09),
        category="saas",
    )

    assert payload["distribution"]["median"] == pytest.approx(0.05)
    assert payload["percentile_rank"] == 50.0
    assert payload["median_comparison"] == "ABOVE"
    assert payload["verdict"] == VERDICT_ABOVE_MEDIAN


def test_benchmark_bottom_quartile() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.02),
        _peers(0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10),
        category="saas",
    )

    assert payload["percentile_rank"] == 0.0
    assert payload["median_comparison"] == "BELOW"
    assert payload["verdict"] == VERDICT_BOTTOM_QUARTILE
    assert any(
        "converted at least as well" in i for i in payload["insights"]
    )
    assert payload["key_signals"][0]["severity"] == "critical"


def test_distribution_percentiles_use_linear_interpolation() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.05),
        _peers(0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10),
        category="saas",
    )

    dist = payload["distribution"]
    assert dist["peer_count"] == 10
    assert dist["min"] == pytest.approx(0.01)
    assert dist["p25"] == pytest.approx(0.0325)
    assert dist["median"] == pytest.approx(0.055)
    assert dist["p75"] == pytest.approx(0.0775)
    assert dist["max"] == pytest.approx(0.10)
    assert dist["mean"] == pytest.approx(0.055)


def test_malformed_peers_are_skipped_and_counted() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.04),
        [
            {"actual_conversion_rate": 0.05, "product_changed_since_sim": False},
            {"actual_conversion_rate": None, "product_changed_since_sim": False},
            {"actual_conversion_rate": "junk", "product_changed_since_sim": False},
            {"actual_conversion_rate": 1.5, "product_changed_since_sim": False},
            {"actual_conversion_rate": -0.1, "product_changed_since_sim": False},
            {"actual_conversion_rate": float("inf"), "product_changed_since_sim": False},
            {"actual_conversion_rate": float("nan"), "product_changed_since_sim": False},
            {"actual_conversion_rate": True, "product_changed_since_sim": False},
        ],
        category="saas",
    )

    assert payload["meta"]["peers_scanned"] == 8
    assert payload["meta"]["peers_usable"] == 1
    assert payload["meta"]["peers_skipped_invalid"] == 7
    assert payload["distribution"]["peer_count"] == 1
    assert payload["verdict"] == VERDICT_BOTTOM_QUARTILE
    assert payload["meta"]["data_sufficient"] is False
    assert any("directional" in i for i in payload["insights"])


def test_product_changed_peers_are_excluded() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.05),
        _peers(0.05, 0.09, changed=[True, True]),
        category="saas",
    )

    assert payload["meta"]["peers_scanned"] == 2
    assert payload["meta"]["peers_skipped_product_changed"] == 2
    assert payload["meta"]["peers_usable"] == 0
    assert payload["verdict"] == VERDICT_INSUFFICIENT_DATA
    assert "No comparable launched outcomes in saas" in payload["insights"][0]


def test_prediction_gap_insight_surfaces_direction() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.06, predicted=0.02),
        _peers(0.03, 0.04),
        category="saas",
    )

    assert any(
        "predicted 2.00%; actual conversion landed 4.00pp higher" in i
        for i in payload["insights"]
    )


def test_prediction_within_half_pp_is_matched() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.051, predicted=0.05),
        _peers(0.03, 0.04),
        category="saas",
    )

    assert any(
        "matched within 0.5pp" in i for i in payload["insights"]
    )


def test_small_cohort_adds_directional_caveat() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.05),
        _peers(0.04),
        category="saas",
    )

    assert payload["meta"]["data_sufficient"] is False
    assert any("Only 1 peer outcome" in i for i in payload["insights"])


def test_current_outcome_is_serialised_defensively() -> None:
    payload = build_outcome_benchmark(
        {
            "id": 12,
            "simulation_id": None,
            "project_id": 10,
            "actual_conversion_rate": 0.05,
            "predicted_conversion_rate": None,
            "days_since_launch": None,
            "data_confidence": None,
            "launched": False,
            "created_at": None,
        },
        [],
        category="hardware",
    )

    current = payload["current"]
    assert current is not None
    assert current["outcome_id"] == 12
    assert current["simulation_id"] is None
    assert current["predicted_conversion_rate"] is None
    assert current["days_since_launch"] == 0
    assert current["data_confidence"] is None
    assert current["recorded_at"] is None


def test_schema_roundtrip_accepts_payload() -> None:
    payload = build_outcome_benchmark(
        _current(actual=0.06),
        _peers(0.01, 0.02, 0.03, 0.04, 0.05),
        category="saas",
    )

    out = OutcomeBenchmarkOut(**payload)
    assert out.has_data is True
    assert out.current is not None
    assert out.percentile_rank == 100.0
    assert out.verdict == VERDICT_TOP_QUARTILE
    assert out.distribution.peer_count == 5
    assert out.meta["data_sufficient"] is True


def test_finite_math_on_all_paths() -> None:
    """Every numeric field stays finite even with extreme inputs."""
    payload = build_outcome_benchmark(
        _current(actual=0.0),
        _peers(0.0, 1.0, 0.5),
        category="saas",
    )

    for value in payload["distribution"].values():
        if value is not None:
            assert math.isfinite(float(value))
    assert payload["percentile_rank"] == pytest.approx(16.67)
    assert payload["verdict"] == VERDICT_BOTTOM_QUARTILE

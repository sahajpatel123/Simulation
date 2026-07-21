"""
Tests for cluster opportunity matrix helpers
(cycle 29 cluster-opportunity-matrix).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.simulation.cluster_opportunity import (
    DEFAULT_BENCHMARK,
    HIGH_WEIGHT,
    LIFT_FRACTION,
    build_cluster_opportunity_matrix,
)


def _results(
    *,
    cr: float = 0.03,
    breakdown: dict[str, Any] | None = None,
    total: int = 10000,
    domain: str = "PricingArchitect",
    product_type: str = "saas",
) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": total,
        "cluster_breakdown": breakdown
        or {
            "high_weight_low_cr": 0.01,
            "high_weight_mid_cr": 0.03,
            "low_weight_high_cr": 0.12,
            "low_weight_low_cr": 0.005,
        },
        "primary_failure_domain": domain,
        "product_type_detected": product_type,
    }


def test_empty_results_yield_zero_state() -> None:
    out = build_cluster_opportunity_matrix(None, simulation_id=1, project_id=2)
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.opportunities == []
    assert out.top_opportunity_cluster is None
    assert out.addressable_lift == 0.0
    assert out.focus_recommendations


def test_json_string_and_garbage_inputs() -> None:
    import json

    ok = build_cluster_opportunity_matrix(
        json.dumps(_results()), simulation_id=1, project_id=1
    )
    assert len(ok.opportunities) == 4
    bad = build_cluster_opportunity_matrix("{nope", simulation_id=1, project_id=1)
    assert bad.opportunities == []


def test_segments_classify_expected_buckets() -> None:
    registry = {
        "high_weight_low_cr": {"name": "HW Low", "population_weight": 0.08},
        "high_weight_mid_cr": {"name": "HW Mid", "population_weight": 0.06},
        "low_weight_high_cr": {"name": "Niche", "population_weight": 0.01},
        "low_weight_low_cr": {"name": "Tail", "population_weight": 0.01},
    }
    out = build_cluster_opportunity_matrix(
        _results(),
        simulation_id=10,
        project_id=3,
        cluster_registry=registry,
        benchmark=0.05,
    )
    by_id = {o.cluster_id: o for o in out.opportunities}
    assert by_id["high_weight_low_cr"].segment == "TRANSFORM"
    assert by_id["high_weight_mid_cr"].segment == "QUICK_WIN"
    assert by_id["low_weight_high_cr"].segment == "NICHE"
    assert by_id["low_weight_low_cr"].segment == "DEPRIORITIZE"


def test_opportunity_score_ranks_high_weight_gaps_first() -> None:
    registry = {
        "a": {"name": "A", "population_weight": 0.10},
        "b": {"name": "B", "population_weight": 0.10},
        "c": {"name": "C", "population_weight": 0.01},
    }
    out = build_cluster_opportunity_matrix(
        _results(
            breakdown={"a": 0.01, "b": 0.04, "c": 0.0},
            cr=0.03,
        ),
        simulation_id=11,
        project_id=3,
        cluster_registry=registry,
    )
    assert out.opportunities[0].cluster_id == "a"
    assert out.top_opportunity_cluster == "a"
    assert out.opportunities[0].opportunity_score > out.opportunities[1].opportunity_score


def test_summaries_override_weights_and_attach_triggers() -> None:
    summaries = [
        {
            "cluster_id": "a",
            "agents_assigned": 8000,
            "agents_converted": 80,
            "conversion_rate": 0.01,
            "primary_drop_trigger": "PricingArchitect",
            "mean_drop_state": "DECIDE",
        },
        {
            "cluster_id": "b",
            "agents_assigned": 2000,
            "agents_converted": 160,
            "conversion_rate": 0.08,
            "primary_drop_trigger": "TrustArchitect",
            "mean_drop_state": "CONSIDER",
        },
    ]
    out = build_cluster_opportunity_matrix(
        _results(breakdown={"a": 0.01, "b": 0.08}),
        simulation_id=12,
        project_id=4,
        cluster_summaries=summaries,
    )
    by_id = {o.cluster_id: o for o in out.opportunities}
    assert by_id["a"].population_weight == pytest.approx(0.8, abs=1e-4)
    assert by_id["a"].primary_drop_trigger == "PricingArchitect"
    assert by_id["a"].mean_drop_state == "DECIDE"
    assert out.meta["cluster_summaries_used"] is True


def test_dict_cluster_breakdown_payloads() -> None:
    out = build_cluster_opportunity_matrix(
        _results(
            breakdown={
                "metro": {"conversion_rate": 0.02, "cluster_name": "Metro Pros"},
            }
        ),
        simulation_id=13,
        project_id=4,
        cluster_registry={"metro": {"name": "ignored", "population_weight": 0.05}},
    )
    assert out.opportunities[0].cluster_name == "Metro Pros"
    assert out.opportunities[0].conversion_rate == 0.02


def test_addressable_lift_positive_when_gaps_exist() -> None:
    registry = {
        "big": {"name": "Big", "population_weight": 0.10},
        "mid": {"name": "Mid", "population_weight": 0.05},
    }
    out = build_cluster_opportunity_matrix(
        _results(breakdown={"big": 0.01, "mid": 0.03}, cr=0.02),
        simulation_id=14,
        project_id=5,
        cluster_registry=registry,
    )
    assert out.addressable_lift > 0
    assert any("addressable" in t.lower() or "quick win" in t.lower() or "strategic" in t.lower()
               for t in out.focus_recommendations)


def test_segment_breakdown_sums_opportunity() -> None:
    registry = {
        "high_weight_low_cr": {"name": "HW Low", "population_weight": 0.08},
        "high_weight_mid_cr": {"name": "HW Mid", "population_weight": 0.06},
        "low_weight_high_cr": {"name": "Niche", "population_weight": 0.01},
        "low_weight_low_cr": {"name": "Tail", "population_weight": 0.01},
    }
    out = build_cluster_opportunity_matrix(
        _results(),
        simulation_id=15,
        project_id=5,
        cluster_registry=registry,
    )
    segs = {s.segment: s for s in out.segment_breakdown}
    assert "TRANSFORM" in segs
    assert "QUICK_WIN" in segs
    assert segs["TRANSFORM"].cluster_count >= 1
    total_opp = sum(o.opportunity_score for o in out.opportunities)
    rolled = sum(s.total_opportunity for s in out.segment_breakdown)
    assert rolled == pytest.approx(total_opp, abs=1e-6)


def test_limit_truncates_ranked_list() -> None:
    breakdown = {f"c{i}": 0.01 + (i * 0.001) for i in range(20)}
    registry = {f"c{i}": {"name": f"C{i}", "population_weight": 0.03} for i in range(20)}
    out = build_cluster_opportunity_matrix(
        _results(breakdown=breakdown),
        simulation_id=16,
        project_id=6,
        cluster_registry=registry,
        limit=5,
    )
    assert len(out.opportunities) == 5


def test_custom_benchmark_changes_gaps() -> None:
    registry = {"x": {"name": "X", "population_weight": 0.05}}
    low = build_cluster_opportunity_matrix(
        _results(breakdown={"x": 0.04}),
        simulation_id=17,
        project_id=6,
        cluster_registry=registry,
        benchmark=0.05,
    )
    high = build_cluster_opportunity_matrix(
        _results(breakdown={"x": 0.04}),
        simulation_id=17,
        project_id=6,
        cluster_registry=registry,
        benchmark=0.10,
    )
    assert high.opportunities[0].conversion_gap > low.opportunities[0].conversion_gap


def test_constants_are_sane() -> None:
    assert 0.01 <= DEFAULT_BENCHMARK <= 0.2
    assert 0.0 < LIFT_FRACTION <= 0.6
    assert HIGH_WEIGHT > 0


def test_schema_round_trip() -> None:
    out = build_cluster_opportunity_matrix(
        _results(),
        simulation_id=20,
        project_id=9,
        signal_quality=0.66,
        cluster_registry={
            "high_weight_low_cr": {"name": "HW Low", "population_weight": 0.08},
            "high_weight_mid_cr": {"name": "HW Mid", "population_weight": 0.06},
            "low_weight_high_cr": {"name": "Niche", "population_weight": 0.01},
            "low_weight_low_cr": {"name": "Tail", "population_weight": 0.01},
        },
    )
    dumped = out.model_dump()
    assert dumped["signal_quality"] == 0.66
    assert dumped["meta"]["benchmark"] == DEFAULT_BENCHMARK
    assert isinstance(dumped["opportunities"], list)
    assert isinstance(dumped["focus_recommendations"], list)

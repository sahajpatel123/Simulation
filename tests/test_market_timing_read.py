"""
Tests for the pure market-timing builder
(``app.simulation.market_timing_read``).
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.market_timing import (
    GATE_ADOPTION,
    GATE_AWARENESS,
    GATE_REGULATORY,
    TIER_ALMOST,
    TIER_BLOCKED,
    TIER_EARLY,
    TIER_READY,
    VALID_GATES,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_CAUTIOUS,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_WAIT,
    MarketTimingOut,
)
from app.simulation.market_timing_read import (
    GATE_ORDER,
    build_market_timing,
)


def _registry(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _timing_metrics(
    *,
    awareness: float = 0.35,
    urgency: float = 0.45,
    switching: float = 0.40,
    budget: float = 0.60,
    adoption: float = 0.40,
    trigger: float = 0.50,
    creation_cost: float = 0.50,
    seasonal: float = 1.00,
    pricing_power: float = 0.60,
    reg_risk: float = 0.10,
    reg_suppressor: float = 1.00,
) -> dict[str, float]:
    return {
        "category_awareness_score": awareness,
        "problem_urgency_intensity": urgency,
        "switching_cost_depth": switching,
        "budget_cycle_alignment": budget,
        "technology_adoption_score": adoption,
        "trigger_event_sensitivity": trigger,
        "category_creation_cost": creation_cost,
        "seasonal_demand_coefficient": seasonal,
        "market_maturity_pricing_power": pricing_power,
        "regulatory_dependency_risk": reg_risk,
        "regulatory_suppressor": reg_suppressor,
    }


def _conductor(specs: dict[str, dict[str, float]]) -> dict[str, Any]:
    return {
        cid: {
            "MarketTimingArchitect": {
                "metrics": metrics,
                "flags": {},
            }
        }
        for cid, metrics in specs.items()
    }


def _build(
    *,
    specs: dict[str, dict[str, float]] | None = None,
    weights: dict[str, float] | None = None,
    product_type: str = "saas",
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
) -> MarketTimingOut:
    specs = specs or {
        "a": _timing_metrics(),
        "b": _timing_metrics(),
        "c": _timing_metrics(),
    }
    weights = weights or {"a": 0.4, "b": 0.4, "c": 0.2}
    if registry is None:
        registry = _registry(
            [
                {
                    "cluster_id": cid,
                    "name": cid.upper(),
                    "population_weight": weights[cid],
                }
                for cid in specs
            ]
        )
    if conductor_results is None:
        conductor_results = _conductor(specs)
    return build_market_timing(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def _high_metrics(**overrides: float) -> dict[str, float]:
    metrics = _timing_metrics(
        awareness=0.90,
        urgency=0.95,
        switching=0.10,
        budget=0.90,
        adoption=0.95,
        trigger=0.70,
        creation_cost=0.10,
        seasonal=1.35,
        pricing_power=1.10,
    )
    metrics.update(overrides)
    return metrics


def _low_metrics() -> dict[str, float]:
    return _timing_metrics(
        awareness=0.15,
        urgency=0.20,
        switching=0.80,
        budget=0.50,
        adoption=0.10,
        trigger=0.30,
        creation_cost=0.85,
        pricing_power=0.45,
    )


def test_happy_path_returns_go_payload() -> None:
    out = _build(
        specs={
            "a": _high_metrics(),
            "b": _high_metrics(),
            "c": _high_metrics(),
        },
        weights={"a": 0.4, "b": 0.4, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_GO
    assert out.timing_index == 0.9175
    assert out.weighted_category_awareness == 0.90
    assert out.weighted_problem_urgency == 0.95
    assert out.weighted_seasonal_coefficient == 1.35
    assert out.ready_share == 1.0
    assert out.almost_ready_share == 0.0
    assert out.early_share == 0.0
    assert out.blocked_share == 0.0
    assert out.primary_gate == GATE_AWARENESS
    assert out.primary_gate_label == "Category awareness"
    assert out.primary_gate_share == 1.0
    assert len(out.cluster_profiles) == 3
    assert all(p.readiness_tier in VALID_TIERS for p in out.cluster_profiles)
    assert all(p.readiness_tier == TIER_READY for p in out.cluster_profiles)
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True
    assert "seasonal_demand_lift" in out.flags
    assert "trigger_sensitive_segments" in out.flags
    assert "regulatory_blocked_market" not in out.flags
    assert out.recommendations
    assert "awareness" in out.recommendations[0].lower()
    assert len(out.top_opportunities) == 3
    assert [t.timing_index for t in out.top_opportunities] == [0.9175] * 3
    assert sum(out.gate_distribution.values()) == 1.0
    assert out.gate_distribution[GATE_AWARENESS] == 1.0


def test_wait_verdict_from_whole_market_unready() -> None:
    out = _build(
        specs={
            "a": _low_metrics(),
            "b": _low_metrics(),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_WAIT
    assert out.timing_index == 0.2125
    assert out.early_share == 1.0
    assert out.ready_share == 0.0
    assert all(p.readiness_tier == TIER_EARLY for p in out.cluster_profiles)
    assert out.primary_gate == GATE_ADOPTION
    assert out.primary_gate_label == "Technology adoption"
    assert "low_category_awareness" in out.flags
    assert "weak_problem_urgency" in out.flags
    assert "category_education_gap" in out.flags
    assert "weak_pricing_power" in out.flags
    assert out.top_opportunities == []


def test_regulatory_block_caps_verdict_to_cautious() -> None:
    out = _build(
        specs={
            "a": _high_metrics(
                regulatory_dependency_risk=0.70,
                regulatory_suppressor=0.40,
            ),
            "b": _high_metrics(),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_CAUTIOUS
    assert out.timing_index == 0.6422
    assert out.blocked_share == 0.5
    assert out.ready_share == 0.5
    assert out.cluster_profiles[0].readiness_tier == TIER_BLOCKED
    assert out.cluster_profiles[1].readiness_tier == TIER_READY
    assert out.cluster_profiles[0].primary_gate == GATE_REGULATORY
    assert out.cluster_profiles[0].primary_gate_score == 1.0
    assert out.primary_gate == GATE_REGULATORY
    assert out.primary_gate_label == "Regulatory pathway"
    assert out.primary_gate_share == 0.5
    assert out.gate_distribution[GATE_REGULATORY] == 0.5
    assert out.gate_distribution[GATE_AWARENESS] == 0.5
    assert out.meta["primary_gate_score"] == 0.55
    assert "regulatory_blocked_market" in out.flags
    assert "Regulatory blockers affect 50%" in out.recommendations[1]
    assert len(out.top_opportunities) == 1
    assert out.top_opportunities[0].cluster_id == "b"


def test_insufficient_data_without_metrics() -> None:
    out = _build(
        specs={"a": {}, "b": {}},
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={
            "a": {"unrelated_metric": 1.0},
            "b": {"unrelated_metric": 1.0},
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.timing_index == 0.4675
    assert out.verdict == VERDICT_CAUTIOUS
    assert out.weighted_category_awareness == 0.35
    assert out.weighted_problem_urgency == 0.45
    assert out.weighted_switching_cost == 0.40
    assert out.weighted_budget_cycle_alignment == 0.60
    assert out.weighted_technology_adoption == 0.40
    assert out.weighted_trigger_sensitivity == 0.50
    assert out.weighted_category_creation_cost == 0.50
    assert out.weighted_seasonal_coefficient == 1.0
    assert out.weighted_pricing_power == 0.60
    assert out.weighted_regulatory_risk == 0.10
    assert out.weighted_regulatory_suppressor == 1.0
    assert all(p.readiness_tier == TIER_ALMOST for p in out.cluster_profiles)
    assert out.primary_gate == GATE_AWARENESS
    assert out.flags == ["low_category_awareness"]


def test_zero_weight_clusters_are_excluded() -> None:
    out = _build(
        specs={
            "a": _high_metrics(),
            "b": _high_metrics(),
        },
        weights={"a": 0.5, "b": 0.5},
        registry=_registry(
            [
                {
                    "cluster_id": "a",
                    "name": "A",
                    "population_weight": 0.5,
                },
                {
                    "cluster_id": "b",
                    "name": "B",
                    "population_weight": 0.0,
                },
            ]
        ),
    )

    assert out.meta["total_clusters"] == 2
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 0.5
    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "a"
    assert out.ready_share == 1.0


def test_top_opportunities_exclude_early_and_blocked() -> None:
    out = _build(
        specs={
            "ready": _high_metrics(),
            "almost": _timing_metrics(),
            "early": _low_metrics(),
            "blocked": _high_metrics(
                regulatory_dependency_risk=0.70,
                regulatory_suppressor=0.40,
            ),
        },
        weights={
            "ready": 0.25,
            "almost": 0.25,
            "early": 0.25,
            "blocked": 0.25,
        },
    )

    assert [t.cluster_id for t in out.top_opportunities] == [
        "ready",
        "almost",
    ]
    assert out.top_opportunities[0].readiness_tier == TIER_READY
    assert out.top_opportunities[1].readiness_tier == TIER_ALMOST
    assert out.top_opportunities[0].primary_gate == GATE_AWARENESS


def test_all_product_types_are_supported() -> None:
    for product_type in (
        "saas",
        "marketplace",
        "iot_hardware",
        "smart_home",
        "d2c",
    ):
        out = _build(
            specs={
                "a": _timing_metrics(),
                "b": _timing_metrics(),
            },
            weights={"a": 0.5, "b": 0.5},
            product_type=product_type,
        )
        assert out.verdict != VERDICT_INSUFFICIENT
        assert out.meta["product_type_supported"] is True
        assert out.product_type == product_type


def test_gate_distribution_is_stable_and_complete() -> None:
    out = _build(
        specs={
            "a": _low_metrics(),
            "b": _high_metrics(),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert set(out.gate_distribution) == VALID_GATES
    assert out.primary_gate in VALID_GATES
    assert sum(out.gate_distribution.values()) == 1.0
    assert out.gate_distribution[GATE_ADOPTION] == 0.5
    assert out.gate_distribution[GATE_AWARENESS] == 0.5
    assert out.primary_gate == GATE_AWARENESS  # tie-break by GATE_ORDER


def test_string_results_json_is_accepted() -> None:
    out = build_market_timing(
        json.dumps({"product_type_detected": "saas"}),
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=_conductor({"a": _high_metrics()}),
        cluster_registry=_registry(
            [
                {
                    "cluster_id": "a",
                    "name": "A",
                    "population_weight": 1.0,
                }
            ]
        ),
    )

    assert out.verdict == VERDICT_GO
    assert out.product_type == "saas"


def test_gate_order_is_complete_and_regulatory_first() -> None:
    assert GATE_ORDER[0] == GATE_REGULATORY
    assert set(GATE_ORDER) == VALID_GATES

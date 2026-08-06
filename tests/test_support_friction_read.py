"""
Tests for the pure support-friction builder
(``app.simulation.support_friction``).
"""
from __future__ import annotations

import json
from typing import Any

from app.schemas.support_friction import (
    DRIVER_BUG,
    DRIVER_DOCS,
    DRIVER_DOWNTIME,
    DRIVER_RESPONSE,
    DRIVER_SELF_SERVE,
    DRIVER_TICKET,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MODERATE,
    VALID_DRIVERS,
    VALID_LEVERS,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_CRITICAL,
    VERDICT_HIGH,
    VERDICT_INSUFFICIENT,
    VERDICT_LOW_BURDEN,
    VERDICT_MODERATE,
    SupportFrictionOut,
)
from app.simulation.support_friction import (
    DRIVER_ORDER,
    _friction_index,
    _friction_tier,
    build_support_friction,
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


def _friction_metrics(
    *,
    ticket: float = 0.25,
    self_serve: float = 0.50,
    tolerance: float = 12.0,
    bug: float = 2.0,
    downtime: float = 0.30,
    doc: float = 0.0,
) -> dict[str, float]:
    return {
        "support_ticket_likelihood": ticket,
        "self_serve_resolution_rate": self_serve,
        "response_time_tolerance_hours": tolerance,
        "bug_tolerance_threshold": bug,
        "downtime_sensitivity": downtime,
        "documentation_quality_perception_effect": doc,
    }


def _conductor(
    specs: dict[str, dict[str, float]],
    flags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = flags or {}
    return {
        cid: {
            "SupportFrictionArchitect": {
                "metrics": metrics,
                "flags": {key: True for key in flags.get(cid, [])},
            }
        }
        for cid, metrics in specs.items()
    }


def _build(
    *,
    specs: dict[str, dict[str, float]] | None = None,
    weights: dict[str, float] | None = None,
    product_type: str | None = None,
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
    flags: dict[str, list[str]] | None = None,
    results: dict[str, Any] | None = None,
) -> SupportFrictionOut:
    specs = specs or {
        "a": _friction_metrics(),
        "b": _friction_metrics(),
        "c": _friction_metrics(),
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
        conductor_results = _conductor(specs, flags)
    return build_support_friction(
        results if results is not None else {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_low_burden_payload() -> None:
    out = _build(
        specs={
            "a": _friction_metrics(
                ticket=0.10, self_serve=0.75, tolerance=24.0,
                bug=4.0, downtime=0.20, doc=0.30,
            ),
            "b": _friction_metrics(
                ticket=0.12, self_serve=0.80, tolerance=24.0,
                bug=5.0, downtime=0.15, doc=0.30,
            ),
            "c": _friction_metrics(
                ticket=0.08, self_serve=0.70, tolerance=16.0,
                bug=4.0, downtime=0.10, doc=0.25,
            ),
        },
        weights={"a": 0.5, "b": 0.3, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_LOW_BURDEN
    assert out.friction_index == 0.0587
    assert out.weighted_ticket_likelihood == 0.102
    assert out.weighted_self_serve_resolution_rate == 0.755
    assert out.weighted_response_time_tolerance_hours == 22.4
    assert out.weighted_bug_tolerance_threshold == 4.3
    assert out.weighted_downtime_sensitivity == 0.165
    assert out.weighted_documentation_effect == 0.29
    assert out.low_share == 1.0
    assert out.moderate_share == 0.0
    assert out.high_share == 0.0
    assert out.critical_share == 0.0
    assert out.primary_driver == DRIVER_DOWNTIME
    assert out.primary_driver_share == 0.8
    assert out.estimated_monthly_contacts_per_10k_users == 250
    assert out.estimated_support_agents_per_10k_users == 0.5
    assert len(out.cluster_profiles) == 3
    assert all(p.friction_tier in VALID_TIERS for p in out.cluster_profiles)
    assert all(p.primary_driver in VALID_DRIVERS for p in out.cluster_profiles)
    assert len(out.levers) == 6
    assert all(lever.key in VALID_LEVERS for lever in out.levers)
    assert out.flags == []
    assert out.recommendations
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0


def test_critical_cluster_produces_critical_verdict() -> None:
    out = _build(
        specs={
            "a": _friction_metrics(
                ticket=0.60, self_serve=0.10, tolerance=1.0,
                bug=1.0, downtime=0.80, doc=-0.20,
            )
        },
        weights={"a": 1.0},
        flags={"a": ["phone_support_required", "high_ticket_rate"]},
    )

    assert out.verdict == VERDICT_CRITICAL
    assert out.friction_index == 0.7268
    assert out.critical_share == 1.0
    assert out.primary_driver == DRIVER_DOCS
    assert out.primary_driver_share == 1.0
    assert out.estimated_monthly_contacts_per_10k_users == 5400
    assert out.estimated_support_agents_per_10k_users == 10.8
    assert out.cluster_profiles[0].friction_tier == TIER_CRITICAL
    assert out.cluster_profiles[0].architect_flags == [
        "high_ticket_rate",
        "phone_support_required",
    ]
    assert "critical_friction_clusters" in out.flags
    assert "ticket_volume_high" in out.flags
    assert "self_serve_low" in out.flags
    assert "phone_support_required" in out.flags
    assert "response_tolerance_tight" in out.flags
    assert "downtime_sensitive_market" in out.flags
    assert "low_bug_tolerance" in out.flags
    assert "documentation_gap" in out.flags


def test_no_metrics_returns_insufficient_data() -> None:
    out = _build(conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.levers == []
    assert out.recommendations
    assert out.meta["covered_clusters"] == 0
    assert out.meta["covered_weight"] == 0.0


def test_zero_weight_clusters_are_excluded() -> None:
    specs = {
        "a": _friction_metrics(ticket=0.05, self_serve=0.80, tolerance=24.0),
        "zero": _friction_metrics(ticket=0.90, self_serve=0.05),
    }
    out = _build(
        specs=specs,
        weights={"a": 1.0, "zero": 0.0},
    )

    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "a"
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 1.0
    assert out.verdict == VERDICT_LOW_BURDEN


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={"a": {"support_ticket_likelihood": 0.40}},
        weights={"a": 1.0},
    )

    profile = out.cluster_profiles[0]
    assert profile.self_serve_resolution_rate == 0.5
    assert profile.response_time_tolerance_hours == 12.0
    assert profile.bug_tolerance_threshold == 2.0
    assert profile.downtime_sensitivity == 0.3
    assert profile.documentation_quality_perception_effect == 0.0
    assert out.verdict == VERDICT_LOW_BURDEN


def test_malformed_results_are_tolerated() -> None:
    out = _build(
        specs={"a": _friction_metrics()},
        weights={"a": 1.0},
        results='{"product_type_detected": "marketplace"}',
    )
    assert out.product_type == "marketplace"
    assert out.verdict != VERDICT_INSUFFICIENT

    out_none = _build(
        specs={"a": _friction_metrics()},
        weights={"a": 1.0},
        results=None,
    )
    assert out_none.product_type == "saas"
    assert out_none.verdict != VERDICT_INSUFFICIENT


def test_driver_distribution_sums_to_one_and_is_stable() -> None:
    specs = {
        "ticket_cluster": _friction_metrics(
            ticket=0.90, self_serve=0.45, tolerance=8.0,
            bug=3.0, downtime=0.0, doc=0.30,
        ),
        "self_cluster": _friction_metrics(
            ticket=0.05, self_serve=0.10, tolerance=24.0,
            bug=3.0, downtime=0.0, doc=0.30,
        ),
        "response_cluster": _friction_metrics(
            ticket=0.05, self_serve=0.45, tolerance=1.0,
            bug=3.0, downtime=0.0, doc=0.30,
        ),
    }
    out = _build(
        specs=specs,
        weights={
            "ticket_cluster": 0.5,
            "self_cluster": 0.3,
            "response_cluster": 0.2,
        },
    )

    assert out.cluster_profiles[0].primary_driver == DRIVER_TICKET
    assert out.cluster_profiles[1].primary_driver == DRIVER_SELF_SERVE
    assert out.cluster_profiles[2].primary_driver == DRIVER_RESPONSE
    assert sum(out.driver_distribution.values()) == 1.0
    assert out.primary_driver == DRIVER_TICKET
    assert out.primary_driver_share == 0.5
    assert set(out.driver_distribution) == set(DRIVER_ORDER)


def test_tier_boundaries_are_stable() -> None:
    assert _friction_tier(0.29) == TIER_LOW
    assert _friction_tier(0.30) == TIER_MODERATE
    assert _friction_tier(0.40) == TIER_HIGH
    assert _friction_tier(0.50) == TIER_CRITICAL


def test_friction_index_is_weighted_composite() -> None:
    sevs = {
        DRIVER_TICKET: 1.0,
        DRIVER_SELF_SERVE: 1.0,
        DRIVER_RESPONSE: 1.0,
        DRIVER_BUG: 1.0,
        DRIVER_DOWNTIME: 1.0,
        DRIVER_DOCS: 1.0,
    }
    assert _friction_index(sevs) == 1.0
    assert _friction_index({key: 0.0 for key in sevs}) == 0.0


def test_moderate_and_high_verdicts() -> None:
    moderate = _build(
        specs={
            "a": _friction_metrics(
                ticket=0.35, self_serve=0.30, tolerance=6.0,
                bug=1.0, downtime=0.40, doc=0.10,
            )
        },
        weights={"a": 1.0},
    )
    assert moderate.verdict == VERDICT_MODERATE

    high = _build(
        specs={
            "a": _friction_metrics(
                ticket=0.40, self_serve=0.25, tolerance=4.0,
                bug=1.0, downtime=0.50, doc=0.08,
            )
        },
        weights={"a": 1.0},
    )
    assert high.verdict == VERDICT_HIGH


def test_product_type_is_echoed_and_supported() -> None:
    out = _build(
        specs={"a": _friction_metrics()},
        weights={"a": 1.0},
        product_type="iot_hardware",
    )
    assert out.product_type == "iot_hardware"
    assert out.meta["product_type_supported"] is True


def test_conductor_stack_includes_support_friction_for_all_product_types() -> None:
    from app.simulation.conductor import ARCHITECT_STACKS
    from app.simulation.product_type import ProductType

    for product_type in ProductType:
        assert (
            "SupportFrictionArchitect" in ARCHITECT_STACKS[product_type]
        ), product_type.value


def test_meta_surface() -> None:
    out = _build(
        specs={"a": _friction_metrics()},
        weights={"a": 1.0},
    )
    assert out.meta["signal_quality"] == 0.62
    assert out.meta["contacts_per_agent_month"] == 500.0
    assert out.meta["thresholds"]["tier_low_index"] == 0.30
    assert out.meta["thresholds"]["verdict_high_index"] == 0.50
    assert "primary_driver_score" in out.meta

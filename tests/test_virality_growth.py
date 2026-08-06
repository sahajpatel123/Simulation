"""
Tests for the pure virality-growth builder
(``app.simulation.virality_growth``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.virality_growth import (
    BLOCKER_INVITE,
    BLOCKER_TRIGGER,
    TIER_EMERGING,
    TIER_PROMISING,
    TIER_VIRAL,
    TIER_WEAK,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_INSUFFICIENT,
    VERDICT_LIMITED,
    VERDICT_MOMENTUM,
    VERDICT_VIRAL,
    ViralityGrowthOut,
)
from app.simulation.virality_growth import (
    BLOCKER_ORDER,
    VIRALITY_PRODUCT_TYPES,
    build_virality_growth,
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


def _virality_metrics(
    *,
    k: float = 0.35,
    trigger: float = 0.15,
    incentive: float = 0.50,
    wom: float = 1.0,
    network: float = 100.0,
    invite: float = 0.50,
    content: float = 0.12,
    community: float = 0.20,
) -> dict[str, float]:
    return {
        "viral_coefficient": k,
        "organic_referral_trigger_score": trigger,
        "referral_incentive_response_quality": incentive,
        "word_of_mouth_coefficient": wom,
        "network_effect_threshold": network,
        "invite_completion_rate": invite,
        "content_virality_rate": content,
        "community_building_participation": community,
    }


def _conductor(specs: dict[str, dict[str, float]]) -> dict[str, Any]:
    return {
        cid: {
            "ViralityArchitect": {
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
) -> ViralityGrowthOut:
    specs = specs or {
        "a": _virality_metrics(),
        "b": _virality_metrics(k=0.55, trigger=0.20, invite=0.60),
        "c": _virality_metrics(k=0.20, trigger=0.08, incentive=0.35),
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
    return build_virality_growth(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_ranked_growth_payload() -> None:
    out = _build(
        specs={
            "a": _virality_metrics(
                k=1.4, trigger=0.30, invite=0.70,
                incentive=0.60, wom=1.6, content=0.20, community=0.30,
            ),
            "b": _virality_metrics(
                k=1.1, trigger=0.20, invite=0.60,
                incentive=0.50, wom=1.2, content=0.15, community=0.25,
            ),
            "c": _virality_metrics(
                k=0.9, trigger=0.12, invite=0.45,
                incentive=0.40, wom=0.9, content=0.10, community=0.18,
            ),
        },
        weights={"a": 0.4, "b": 0.4, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_VIRAL
    assert out.weighted_viral_coefficient == 1.18
    assert out.viral_share == 0.8
    assert out.momentum_share == 1.0
    assert len(out.cluster_profiles) == 3
    assert all(p.growth_tier in VALID_TIERS for p in out.cluster_profiles)
    assert out.cluster_profiles[0].growth_tier == TIER_VIRAL
    assert out.cluster_profiles[1].growth_tier == TIER_VIRAL
    assert out.cluster_profiles[2].growth_tier == TIER_PROMISING
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True
    assert len(out.levers) == 6
    assert [lever.opportunity_share for lever in out.levers] == sorted(
        [lever.opportunity_share for lever in out.levers], reverse=True
    )
    assert "viral_loop_possible" in out.flags
    assert out.recommendations
    assert sum(out.blocker_distribution.values()) > 0.99


def test_momentum_verdict_from_viral_share() -> None:
    out = _build(
        specs={
            "a": _virality_metrics(k=0.10),
            "b": _virality_metrics(k=1.10, trigger=0.25, invite=0.65),
        },
        weights={"a": 0.7, "b": 0.3},
    )

    assert out.weighted_viral_coefficient == 0.40
    assert out.viral_share == 0.3
    assert out.verdict == VERDICT_MOMENTUM


def test_low_k_verdict_limited() -> None:
    out = _build(
        specs={
            "a": _virality_metrics(
                k=0.10, trigger=0.05,
                incentive=0.30, content=0.05, community=0.10,
            ),
            "b": _virality_metrics(
                k=0.20, trigger=0.08,
                incentive=0.35, content=0.08, community=0.15,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_LIMITED
    assert out.weighted_viral_coefficient == 0.15
    assert "limited" in out.recommendations[0]
    assert "low_organic_trigger" in out.flags
    assert "incentive_quality_risk" in out.flags
    assert "content_gap" in out.flags
    assert "community_gap" in out.flags


def test_primary_blocker_attribution_and_distribution() -> None:
    out = _build(
        specs={
            "a": _virality_metrics(
                trigger=0.05, invite=0.60,
                incentive=0.50, wom=1.0, content=0.20, community=0.30,
            ),
            "b": _virality_metrics(
                trigger=0.40, invite=0.25,
                incentive=0.60, wom=1.4, content=0.30, community=0.40,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.primary_blocker == BLOCKER_TRIGGER
    assert out.primary_blocker_label == "Organic sharing trigger"
    assert out.cluster_profiles[0].primary_blocker == BLOCKER_TRIGGER
    assert out.cluster_profiles[1].primary_blocker == BLOCKER_INVITE
    assert sum(out.blocker_distribution.values()) > 0.99
    assert any("Organic sharing trigger" in r for r in out.recommendations)


def test_missing_metrics_use_conservative_defaults() -> None:
    out = _build(
        specs={
            "a": {"viral_coefficient": 0.10},
            "b": {"viral_coefficient": 0.20},
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.weighted_viral_coefficient == 0.15
    assert out.weighted_organic_trigger == 0.05
    assert out.weighted_invite_completion == 0.30
    assert out.weighted_incentive_quality == 0.40
    assert out.weighted_wom_coefficient == 0.50
    assert out.weighted_content_virality == 0.05
    assert out.weighted_community_participation == 0.10
    assert out.verdict == VERDICT_LIMITED
    assert all(p.growth_tier == TIER_WEAK for p in out.cluster_profiles)
    assert all(p.primary_blocker == BLOCKER_TRIGGER for p in out.cluster_profiles)
    assert len(out.levers) == 6


def test_entirely_empty_metric_blocks_are_skipped() -> None:
    out = _build(
        specs={"a": {}, "b": {}},
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(product_type="enterprise_software")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.cluster_profiles == []
    assert out.recommendations
    assert "enterprise_software" in out.recommendations[0]


def test_empty_registry_returns_insufficient_data() -> None:
    out = _build(registry=[])

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations


def test_missing_architect_blocks_are_skipped() -> None:
    out = _build(
        specs={"a": _virality_metrics(k=1.2)},
        weights={"a": 1.0},
        conductor_results={
            "a": {},
            "b": {
                "ViralityArchitect": {
                    "metrics": _virality_metrics(k=2.0),
                    "flags": {},
                }
            },
        },
        registry=_registry(
            [
                {"cluster_id": "a", "name": "A", "population_weight": 0.5},
                {"cluster_id": "b", "name": "B", "population_weight": 0.5},
            ]
        ),
    )

    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 0.5
    assert out.weighted_viral_coefficient == 2.0
    assert out.verdict == VERDICT_VIRAL


def test_supported_product_types_include_virality_stacks() -> None:
    assert {"saas", "marketplace", "mobile_app", "developer_tool"} <= VIRALITY_PRODUCT_TYPES
    assert {"consumer_hardware", "health_hardware", "consumer_app", "d2c"} <= VIRALITY_PRODUCT_TYPES
    assert {"b2b_marketplace", "productivity_tool"} <= VIRALITY_PRODUCT_TYPES
    assert "enterprise_software" not in VIRALITY_PRODUCT_TYPES
    assert "iot_hardware" not in VIRALITY_PRODUCT_TYPES
    assert "wearable" not in VIRALITY_PRODUCT_TYPES


def test_blocker_order_is_stable_and_complete() -> None:
    assert BLOCKER_ORDER == (
        BLOCKER_TRIGGER,
        BLOCKER_INVITE,
        "incentive_quality",
        "word_of_mouth",
        "content_virality",
        "community",
    )
    assert len(set(BLOCKER_ORDER)) == 6


def test_emerging_tier_mid_k() -> None:
    out = _build(
        specs={
            "a": _virality_metrics(k=0.30),
        },
        weights={"a": 1.0},
    )

    assert out.cluster_profiles[0].growth_tier == TIER_EMERGING
    assert out.verdict == VERDICT_LIMITED

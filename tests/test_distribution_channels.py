"""
Tests for the pure distribution-channels builder
(``app.simulation.distribution_channels``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.distribution_channels import (
    BLOCKER_ACCESS,
    BLOCKER_DELIVERY,
    BLOCKER_TRY_BEFORE_BUY,
    TIER_ACCESS_GAP,
    TIER_LIMITED_ACCESS,
    TIER_OMNICHANNEL,
    TIER_ONLINE,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_ACCESS_GAP,
    VERDICT_INSUFFICIENT,
    VERDICT_OMNICHANNEL,
    VERDICT_ONLINE_FIRST,
    DistributionChannelsOut,
)
from app.simulation.distribution_channels import (
    BLOCKER_ORDER,
    DISTRIBUTION_PRODUCT_TYPES,
    build_distribution_channels,
)
from app.simulation.architects.distribution_channel import DistributionChannelArchitect
from app.simulation.conductor import ARCHITECT_STACKS


def _registry(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _distribution_metrics(
    *,
    access: float = 1.0,
    online_pref: float = 0.72,
    days: float = 2.0,
    try_before_buy: float = 0.30,
    influencer: float = 0.20,
    cashback: float = 0.30,
    amazon: float = 0.40,
    flipkart: float = 0.30,
    brand_direct: float = 0.20,
    offline: float = 0.40,
) -> dict[str, float]:
    return {
        "online_preference": online_pref,
        "distribution_accessibility_multiplier": access,
        "delivery_speed_days_required": days,
        "try_before_buy_requirement": try_before_buy,
        "influencer_review_dependency": influencer,
        "cashback_loyalty_sensitivity": cashback,
        "platform_pref_amazon": amazon,
        "platform_pref_flipkart": flipkart,
        "platform_pref_brand_direct": brand_direct,
        "platform_pref_offline": offline,
    }


def _conductor(
    specs: dict[str, dict[str, float]],
    flags: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        cid: {
            "DistributionChannelArchitect": {
                "metrics": metrics,
                "flags": (flags or {}).get(cid, {}),
            }
        }
        for cid, metrics in specs.items()
    }


def _build(
    *,
    specs: dict[str, dict[str, float]] | None = None,
    weights: dict[str, float] | None = None,
    product_type: str = "consumer_hardware",
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
    flags: dict[str, dict[str, Any]] | None = None,
) -> DistributionChannelsOut:
    specs = specs or {
        "a": _distribution_metrics(),
        "b": _distribution_metrics(access=0.55, offline=0.20),
        "c": _distribution_metrics(access=0.30, offline=0.10),
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
        conductor_results = _conductor(specs, flags=flags)
    return build_distribution_channels(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_ranked_distribution_payload() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(
                access=1.0, online_pref=0.60, offline=0.55,
            ),
            "b": _distribution_metrics(
                access=1.0, online_pref=0.80, offline=0.20,
            ),
            "c": _distribution_metrics(
                access=0.30, online_pref=0.40, offline=0.10,
            ),
        },
        weights={"a": 0.4, "b": 0.4, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "consumer_hardware"
    assert out.verdict == VERDICT_ACCESS_GAP
    assert out.weighted_accessibility == 0.86
    assert out.access_gap_share == 0.2
    assert out.weighted_platform_offline == 0.32
    assert len(out.cluster_profiles) == 3
    assert len(out.levers) == 6
    assert out.primary_blocker == "platform_presence"
    assert out.recommendations
    assert out.meta["total_clusters"] == 3
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True


def test_omnichannel_market_returns_omnichannel_verdict() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(
                access=1.0, online_pref=0.55, offline=0.60,
            ),
            "b": _distribution_metrics(
                access=1.0, online_pref=0.65, offline=0.50,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_OMNICHANNEL
    assert out.omnichannel_share == 1.0
    assert {p.channel_tier for p in out.cluster_profiles} == {TIER_OMNICHANNEL}
    assert "distribution_kill_shot" not in out.flags


def test_online_first_when_access_is_fine_but_offline_is_weak() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(
                access=1.0, online_pref=0.90, offline=0.20,
            ),
            "b": _distribution_metrics(
                access=1.0, online_pref=0.85, offline=0.15,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_ONLINE_FIRST
    assert out.weighted_accessibility == 1.0
    assert out.access_gap_share == 0.0
    assert "no_offline_presence" in out.flags


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(product_type="saas")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.cluster_profiles == []
    assert "saas" in out.recommendations[0]


def test_missing_conductor_metrics_returns_insufficient_data() -> None:
    out = _build(
        specs={"a": _distribution_metrics()},
        weights={"a": 1.0},
        conductor_results={},
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert "no per-cluster" in out.recommendations[0].lower()


def test_missing_fields_use_conservative_defaults() -> None:
    partial = {
        "online_preference": 0.72,
    }
    out = _build(
        specs={"a": partial},
        weights={"a": 1.0},
        conductor_results={"a": {"DistributionChannelArchitect": {"metrics": partial, "flags": {}}}},
    )

    assert out.verdict == VERDICT_ACCESS_GAP
    profile = out.cluster_profiles[0]
    assert profile.distribution_accessibility_multiplier == 0.0
    assert profile.channel_tier == TIER_ACCESS_GAP
    assert profile.primary_blocker == BLOCKER_ACCESS
    assert out.weighted_platform_amazon == 0.0
    assert out.flags == ["distribution_kill_shot", "no_offline_presence"]


def test_delivery_blocker_attribution_is_population_weighted() -> None:
    out = _build(
        specs={
            "slow": _distribution_metrics(access=1.0, days=5.0),
            "fast": _distribution_metrics(access=1.0, days=1.0),
        },
        weights={"slow": 0.7, "fast": 0.3},
    )

    slow = next(p for p in out.cluster_profiles if p.cluster_id == "slow")
    assert slow.primary_blocker == BLOCKER_DELIVERY
    assert out.primary_blocker == BLOCKER_DELIVERY
    assert out.primary_blocker_share == 0.7
    assert out.weighted_delivery_days == 3.8
    assert "delivery_sensitive" in out.flags
    assert "Delivery speed" in out.primary_blocker_label


def test_try_before_buy_blocker_and_flag() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(access=1.0, try_before_buy=0.75),
            "b": _distribution_metrics(access=1.0, try_before_buy=0.10),
        },
        weights={"a": 0.5, "b": 0.5},
        flags={"a": {"try_before_buy_critical": True}},
    )

    a = next(p for p in out.cluster_profiles if p.cluster_id == "a")
    assert a.primary_blocker == BLOCKER_TRY_BEFORE_BUY
    assert "try_before_buy_critical" in out.flags
    assert any("try-before-buy" in r.lower() for r in out.recommendations)


def test_levers_are_ranked_and_actions_formatted() -> None:
    out = _build(
        specs={
            "gap": _distribution_metrics(access=0.30, amazon=0.70),
            "try": _distribution_metrics(
                access=1.0, try_before_buy=0.80, offline=0.10, amazon=0.70,
            ),
            "ok": _distribution_metrics(
                access=1.0, try_before_buy=0.20, offline=0.60, amazon=0.70,
            ),
        },
        weights={"gap": 0.3, "try": 0.3, "ok": 0.4},
    )

    keys = [lever.key for lever in out.levers]
    assert len(keys) == 6
    assert keys[0] == "offline_distribution"
    assert all(0.0 <= lever.opportunity_share <= 1.0 for lever in out.levers)
    offline = next(l for l in out.levers if l.key == "offline_distribution")
    assert offline.market_value == 0.3
    assert "30%" in offline.action
    try_before_buy = next(l for l in out.levers if l.key == "try_before_buy_program")
    assert try_before_buy.opportunity_share == 0.3
    assert "test first" in try_before_buy.action


def test_kill_shot_flag_surfaces_recommendation() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(access=1.0),
            "b": _distribution_metrics(access=0.30),
        },
        weights={"a": 0.8, "b": 0.2},
        flags={"b": {"distribution_kill_shot": True}},
    )

    assert "distribution_kill_shot" in out.flags
    assert any("cannot reliably access" in r for r in out.recommendations)


def test_supported_product_types_cover_distribution_stacks() -> None:
    assert {
        "consumer_hardware",
        "health_hardware",
        "iot_hardware",
        "wearable",
        "b2b_hardware",
        "smart_home",
    } <= DISTRIBUTION_PRODUCT_TYPES
    assert "saas" not in DISTRIBUTION_PRODUCT_TYPES
    assert "consumer_app" not in DISTRIBUTION_PRODUCT_TYPES


def test_supported_set_matches_conductor_activation() -> None:
    """Every advertised product type must actually run DistributionChannelArchitect."""
    activated = {
        pt.value
        for pt, stack in ARCHITECT_STACKS.items()
        if "DistributionChannelArchitect" in stack
        and pt.value in DistributionChannelArchitect().product_types
    }
    assert DISTRIBUTION_PRODUCT_TYPES == activated


def test_valid_enums_cover_output_values() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(access=1.0, offline=0.55),
            "b": _distribution_metrics(access=0.30, offline=0.10),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict in VALID_VERDICTS
    assert all(p.channel_tier in VALID_TIERS for p in out.cluster_profiles)
    assert out.primary_blocker in BLOCKER_ORDER
    assert {p.channel_tier for p in out.cluster_profiles} >= {
        TIER_OMNICHANNEL,
        TIER_ACCESS_GAP,
    }


def test_limited_access_tier_keeps_partial_access() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(access=0.60, offline=0.20),
        },
        weights={"a": 1.0},
    )

    assert out.cluster_profiles[0].channel_tier == TIER_LIMITED_ACCESS
    assert out.verdict == VERDICT_ACCESS_GAP
    assert out.limited_access_share == 1.0


def test_online_tier_when_accessible_but_no_offline() -> None:
    out = _build(
        specs={
            "a": _distribution_metrics(access=1.0, offline=0.20),
        },
        weights={"a": 1.0},
    )

    assert out.cluster_profiles[0].channel_tier == TIER_ONLINE
    assert out.verdict == VERDICT_ONLINE_FIRST
    assert out.online_share == 1.0

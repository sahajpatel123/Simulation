"""
Tests for the pure ecosystem-compatibility builder
(``app.simulation.ecosystem_compatibility``).
"""
from __future__ import annotations

import functools
from typing import Any

from app.schemas.ecosystem_compatibility import (
    BLOCKER_CLOUD,
    BLOCKER_LOCKIN,
    BLOCKER_SMART_HOME,
    BLOCKER_SUBSCRIPTION,
    BLOCKER_VOICE,
    EcosystemCompatibilityOut,
    LEVER_API,
    LEVER_HOUSEHOLD,
    LEVER_MATTER,
    LEVER_PRIVACY,
    LEVER_SUBSCRIPTION,
    LEVER_VOICE,
    TIER_LOCKED,
    TIER_OPEN,
    TIER_PARTIAL,
    TIER_TETHERED,
    VALID_BLOCKERS,
    VALID_LEVERS,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_BLOCKED,
    VERDICT_FRAGILE,
    VERDICT_INSUFFICIENT,
    VERDICT_SEAMLESS,
    VERDICT_WORKABLE,
)
from app.simulation.conductor import Conductor
from app.simulation.ecosystem_compatibility import (
    BLOCKER_ORDER,
    _compatibility_index,
    _compatibility_tier,
    build_ecosystem_compatibility,
)
from app.simulation.product_type import ProductType


def _registry(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _ecosystem_metrics(
    *,
    lockin_acceptance: float = 0.60,
    smart_home_req: float = 0.30,
    subscription: float = 0.25,
    cloud_tolerance: float = 0.55,
    api_interest: float = 0.20,
    cross_device: float = 0.50,
    household_sharing: float = 0.40,
    voice: float = 0.25,
    gate: float = 0.50,
) -> dict[str, float]:
    return {
        "platform_lockin_acceptance": lockin_acceptance,
        "smart_home_compatibility_requirement": smart_home_req,
        "subscription_hardware_resentment": subscription,
        "cloud_storage_tolerance": cloud_tolerance,
        "developer_api_interest": api_interest,
        "cross_device_interoperability": cross_device,
        "household_sharing_behaviour": household_sharing,
        "voice_assistant_expectation": voice,
        "ecosystem_compatibility_gate": gate,
    }


def _conductor(
    specs: dict[str, dict[str, Any]],
    flags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = flags or {}
    return {
        cid: {
            "EcosystemCompatibilityArchitect": {
                "metrics": metrics,
                "flags": {key: True for key in flags.get(cid, [])},
            }
        }
        for cid, metrics in specs.items()
    }


def _build(
    *,
    specs: dict[str, dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
    product_type: str | None = None,
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
    flags: dict[str, list[str]] | None = None,
    results: dict[str, Any] | None = None,
) -> EcosystemCompatibilityOut:
    specs = specs or {
        "a": _ecosystem_metrics(),
        "b": _ecosystem_metrics(),
        "c": _ecosystem_metrics(),
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
    return build_ecosystem_compatibility(
        results if results is not None else {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_seamless_payload() -> None:
    out = _build(
        specs={
            "a": _ecosystem_metrics(
                lockin_acceptance=0.95, smart_home_req=0.10,
                subscription=0.05, cloud_tolerance=0.85,
                api_interest=0.50, household_sharing=0.40,
                voice=0.10,
            ),
            "b": _ecosystem_metrics(smart_home_req=0.25),
            "c": _ecosystem_metrics(
                lockin_acceptance=0.20, smart_home_req=0.70,
                subscription=0.60, cloud_tolerance=0.20,
                api_interest=0.10, household_sharing=0.10,
                voice=0.50, gate=0.80,
            ),
        },
        weights={"a": 0.5, "b": 0.3, "c": 0.2},
        product_type="iot_hardware",
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "iot_hardware"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_WORKABLE
    assert out.compatibility_index == 0.719
    assert out.weighted_platform_lockin_acceptance == 0.695
    assert out.weighted_smart_home_requirement == 0.265
    assert out.weighted_subscription_resentment == 0.22
    assert out.weighted_cloud_tolerance == 0.63
    assert out.weighted_developer_api_interest == 0.33
    assert out.weighted_cross_device_interoperability == 0.5
    assert out.weighted_household_sharing == 0.34
    assert out.weighted_voice_expectation == 0.225
    assert out.weighted_compatibility_gate == 0.56
    assert out.open_share == 0.5
    assert out.partial_share == 0.3
    assert out.locked_share == 0.2
    assert out.tethered_share == 0.0
    assert out.primary_blocker == BLOCKER_CLOUD
    assert out.primary_blocker_share == 0.8
    assert out.blocker_distribution[BLOCKER_CLOUD] == 0.8
    assert out.blocker_distribution[BLOCKER_LOCKIN] == 0.2
    assert out.meta["primary_blocker_score"] == 0.37
    assert len(out.cluster_profiles) == 3
    assert [p.compatibility_tier for p in out.cluster_profiles] == [
        TIER_OPEN,
        TIER_PARTIAL,
        TIER_LOCKED,
    ]
    assert [p.primary_blocker for p in out.cluster_profiles] == [
        BLOCKER_CLOUD,
        BLOCKER_CLOUD,
        BLOCKER_LOCKIN,
    ]
    assert all(p.primary_blocker in VALID_BLOCKERS for p in out.cluster_profiles)
    assert len(out.levers) == 6
    assert all(lever.key in VALID_LEVERS for lever in out.levers)
    assert out.levers[0].key == LEVER_HOUSEHOLD
    assert out.levers[0].opportunity_share == 0.8
    assert out.levers[1].key == LEVER_API
    assert out.levers[1].opportunity_share == 0.5
    assert out.flags == ["locked_clusters"]
    assert out.recommendations
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["thresholds"]["verdict_workable_index"] == 0.55


def test_locked_cluster_produces_blocked_verdict() -> None:
    out = _build(
        specs={
            "a": _ecosystem_metrics(
                lockin_acceptance=0.10, smart_home_req=0.80,
                subscription=0.70, cloud_tolerance=0.10,
                api_interest=0.50, voice=0.60,
            )
        },
        weights={"a": 1.0},
        flags={"a": ["subscription_resentment_high", "cloud_privacy_concern"]},
    )

    assert out.verdict == VERDICT_BLOCKED
    assert out.compatibility_index == 0.205
    assert out.locked_share == 1.0
    assert out.primary_blocker == BLOCKER_LOCKIN
    assert out.primary_blocker_share == 1.0
    assert out.cluster_profiles[0].compatibility_tier == TIER_LOCKED
    assert out.cluster_profiles[0].architect_flags == [
        "cloud_privacy_concern",
        "subscription_resentment_high",
    ]
    assert out.flags == [
        "locked_clusters",
        "platform_lockin_market",
        "smart_home_gate_market",
        "subscription_resentment_market",
        "cloud_privacy_market",
        "voice_expectation_market",
    ]
    assert all(lever.opportunity_share == 1.0 for lever in out.levers)
    assert out.levers[0].key == LEVER_HOUSEHOLD
    assert "launch blocker" in out.recommendations[0]


def test_no_metrics_returns_insufficient_data() -> None:
    out = _build(conductor_results={}, product_type="saas")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.levers == []
    assert out.recommendations
    assert out.meta["covered_clusters"] == 0
    assert out.meta["covered_weight"] == 0.0
    assert out.meta["product_type_supported"] is False
    assert "consumer_hardware" in out.recommendations[0]


def test_saas_product_type_is_insufficient() -> None:
    out = _build(product_type="saas", conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.meta["covered_clusters"] == 0


def test_zero_weight_clusters_are_excluded() -> None:
    specs = {
        "a": _ecosystem_metrics(
            lockin_acceptance=0.95, smart_home_req=0.05,
            subscription=0.05, cloud_tolerance=0.90, voice=0.05,
        ),
        "zero": _ecosystem_metrics(
            lockin_acceptance=0.05, smart_home_req=0.95,
            subscription=0.95, cloud_tolerance=0.05, voice=0.95,
        ),
    }
    out = _build(
        specs=specs,
        weights={"a": 1.0, "zero": 0.0},
        product_type="wearable",
    )

    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "a"
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 1.0
    assert out.verdict == VERDICT_SEAMLESS


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={"a": {"platform_lockin_acceptance": 0.90}},
        weights={"a": 1.0},
        product_type="consumer_hardware",
    )

    profile = out.cluster_profiles[0]
    assert profile.platform_lockin_acceptance == 0.9
    assert profile.smart_home_compatibility_requirement == 0.25
    assert profile.subscription_hardware_resentment == 0.25
    assert profile.cloud_storage_tolerance == 0.55
    assert profile.developer_api_interest == 0.2
    assert profile.cross_device_interoperability == 0.5
    assert profile.household_sharing_behaviour == 0.35
    assert profile.voice_assistant_expectation == 0.25
    assert profile.ecosystem_compatibility_gate == 0.5
    assert profile.compatibility_index == 0.7475
    assert profile.compatibility_tier == TIER_PARTIAL
    assert out.verdict == VERDICT_WORKABLE


def test_partial_metrics_do_not_manufacture_levers_or_flags() -> None:
    """A payload missing most fields must stay friction-neutral: the
    neutral defaults sit below every lever/flag trigger, so the read
    never invents a smart-home gate market, a Matter lever, or a
    household-design lever from absent data."""
    out = _build(
        specs={"a": {"platform_lockin_acceptance": 0.90}},
        weights={"a": 1.0},
        product_type="consumer_hardware",
    )

    assert out.flags == []
    lever_shares = {lever.key: lever.opportunity_share for lever in out.levers}
    assert lever_shares[LEVER_MATTER] == 0.0
    assert lever_shares[LEVER_HOUSEHOLD] == 0.0
    assert all(share == 0.0 for share in lever_shares.values())
    assert out.weighted_smart_home_requirement == 0.25
    assert out.weighted_household_sharing == 0.35


def test_malformed_results_are_tolerated() -> None:
    out = _build(
        specs={"a": _ecosystem_metrics()},
        weights={"a": 1.0},
        results='{"product_type_detected": "iot_hardware"}',
        product_type="iot_hardware",
    )
    assert out.product_type == "iot_hardware"
    assert out.verdict != VERDICT_INSUFFICIENT

    out_none = _build(
        specs={"a": _ecosystem_metrics()},
        weights={"a": 1.0},
        results=None,
        conductor_results={},
    )
    assert out_none.product_type == "saas"
    assert out_none.verdict == VERDICT_INSUFFICIENT


def test_blocker_distribution_sums_to_one_and_is_stable() -> None:
    specs = {
        "lockin_cluster": _ecosystem_metrics(
            lockin_acceptance=0.20, smart_home_req=0.10,
            subscription=0.10, cloud_tolerance=0.80, voice=0.10,
        ),
        "subscription_cluster": _ecosystem_metrics(
            lockin_acceptance=0.80, smart_home_req=0.10,
            subscription=0.80, cloud_tolerance=0.80, voice=0.10,
        ),
        "voice_cluster": _ecosystem_metrics(
            lockin_acceptance=0.80, smart_home_req=0.10,
            subscription=0.10, cloud_tolerance=0.80, voice=0.70,
        ),
    }
    out = _build(
        specs=specs,
        weights={
            "lockin_cluster": 0.5,
            "subscription_cluster": 0.3,
            "voice_cluster": 0.2,
        },
        product_type="health_hardware",
    )

    assert out.cluster_profiles[0].primary_blocker == BLOCKER_LOCKIN
    assert out.cluster_profiles[1].primary_blocker == BLOCKER_SUBSCRIPTION
    assert out.cluster_profiles[2].primary_blocker == BLOCKER_VOICE
    assert sum(out.blocker_distribution.values()) == 1.0
    assert out.primary_blocker == BLOCKER_LOCKIN
    assert out.primary_blocker_share == 0.5
    assert set(out.blocker_distribution) == set(BLOCKER_ORDER)


def test_ties_resolve_to_platform_lockin() -> None:
    # Every severity is exactly 0.30: the read must point at the first
    # blocker in BLOCKER_ORDER (platform lock-in) instead of an
    # arbitrary one.
    out = _build(
        specs={
            "a": _ecosystem_metrics(
                lockin_acceptance=0.70, smart_home_req=0.30,
                subscription=0.30, cloud_tolerance=0.70, voice=0.30,
            )
        },
        weights={"a": 1.0},
        product_type="consumer_hardware",
    )

    assert out.primary_blocker == BLOCKER_LOCKIN
    assert out.cluster_profiles[0].primary_blocker == BLOCKER_LOCKIN
    assert out.cluster_profiles[0].primary_blocker_score == 0.3


def test_architect_smart_home_activation_is_real() -> None:
    """smart_home is a supported product type: EcosystemCompatibilityArchitect
    must actually run in the conductor stack for it."""
    result = Conductor().run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[{"text": "smart home device with Matter support"}],
        product_type=ProductType.SMART_HOME,
    )
    first_cluster = next(iter(result.cluster_results.values()))
    assert "EcosystemCompatibilityArchitect" in first_cluster
    assert all(
        "EcosystemCompatibilityArchitect" in cluster_outputs
        for cluster_outputs in result.cluster_results.values()
    )
    assert any(
        cluster_outputs["EcosystemCompatibilityArchitect"].metrics[
            "smart_home_compatibility_requirement"
        ]
        > 0.0
        for cluster_outputs in result.cluster_results.values()
    )


def test_real_conductor_hardware_run_is_covered() -> None:
    result = _cached_hardware_conductor()
    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in result.cluster_results.items()
    }
    from app.simulation.clusters.registry import ClusterRegistry

    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in ClusterRegistry().all_clusters()
    ]
    out = build_ecosystem_compatibility(
        {"product_type_detected": "consumer_hardware"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type="consumer_hardware",
    )

    assert out.verdict != VERDICT_INSUFFICIENT
    assert out.verdict in {VERDICT_SEAMLESS, VERDICT_WORKABLE, VERDICT_FRAGILE, VERDICT_BLOCKED}
    assert 0.0 <= out.compatibility_index <= 1.0
    assert len(out.cluster_profiles) == len(registry)
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == out.meta["total_clusters"]
    assert out.meta["covered_weight"] > 0.9
    assert len(out.levers) == 6
    assert out.recommendations


def test_index_and_tier_helpers_are_clamped() -> None:
    assert _compatibility_index({BLOCKER_LOCKIN: 0.0}) == 1.0
    assert _compatibility_index(
        {
            BLOCKER_LOCKIN: 1.0,
            BLOCKER_SMART_HOME: 1.0,
            BLOCKER_SUBSCRIPTION: 1.0,
            BLOCKER_CLOUD: 1.0,
            BLOCKER_VOICE: 1.0,
        }
    ) < 1e-9
    assert _compatibility_tier(0.80) == TIER_OPEN
    assert _compatibility_tier(0.60) == TIER_PARTIAL
    assert _compatibility_tier(0.45) == TIER_TETHERED
    assert _compatibility_tier(0.20) == TIER_LOCKED


@functools.lru_cache(maxsize=1)
def _cached_hardware_conductor() -> object:
    """One real deterministic consumer_hardware run, shared by tests."""
    return Conductor().run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[],
        product_type=ProductType.CONSUMER_HARDWARE,
    )

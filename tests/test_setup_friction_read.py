"""
Tests for the pure setup-friction builder
(``app.simulation.setup_friction``).
"""
from __future__ import annotations

import functools
from typing import Any

from app.schemas.setup_friction import (
    BLOCKER_COMPANION_APP,
    BLOCKER_FIRMWARE_UPDATE,
    BLOCKER_PAIRING,
    BLOCKER_SETUP_COMPLETION,
    BLOCKER_TIME_TO_VALUE,
    LEVER_ACCOUNT_OPTIONAL,
    LEVER_COMPANION_APP,
    LEVER_GUIDED_SETUP,
    LEVER_ONBOARDING_WIZARD,
    LEVER_ONE_TAP_PAIRING,
    LEVER_PREFLASHED_FIRMWARE,
    LEVER_PRINTED_GUIDE,
    LEVER_SIMPLIFIED_ASSEMBLY,
    TIER_BLOCKED,
    TIER_ROUGH,
    TIER_SEAMLESS,
    TIER_SLOW,
    VALID_BLOCKERS,
    VALID_LEVERS,
    VALID_VERDICTS,
    VERDICT_ACCEPTABLE,
    VERDICT_BLOCKED,
    VERDICT_FAST,
    VERDICT_INSUFFICIENT,
    VERDICT_SLOW,
    SetupFrictionOut,
)
from app.simulation.conductor import Conductor
from app.simulation.product_type import ProductType
from app.simulation.setup_friction import (
    BLOCKER_ORDER,
    _setup_index,
    _setup_tier,
    build_setup_friction,
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


def _setup_metrics(
    *,
    completion: float = 0.90,
    app_install: float = 0.60,
    abandonment: float = 0.04,
    firmware_tolerance: float = 9.0,
    assembly_tolerance: float = 3.0,
    pairing_tolerance: float = 2.2,
    ttfmu: float = 4.0,
    customisation: float = 0.30,
) -> dict[str, float]:
    return {
        "oob_setup_completion_rate": completion,
        "companion_app_install_rate": app_install,
        "account_creation_abandonment": abandonment,
        "firmware_update_tolerance_min": firmware_tolerance,
        "physical_assembly_tolerance": assembly_tolerance,
        "pairing_friction_tolerance": pairing_tolerance,
        "time_to_first_meaningful_use": ttfmu,
        "initial_customisation_depth": customisation,
    }


def _conductor(
    specs: dict[str, dict[str, Any]],
    flags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = flags or {}
    return {
        cid: {
            "SetupFirstUseArchitect": {
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
    requires_companion_app: bool = False,
) -> SetupFrictionOut:
    specs = specs or {
        "a": _setup_metrics(),
        "b": _setup_metrics(),
        "c": _setup_metrics(),
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
    return build_setup_friction(
        results if results is not None else {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
        requires_companion_app=requires_companion_app,
    )


def test_happy_path_returns_acceptable_payload() -> None:
    out = _build(
        specs={
            "a": _setup_metrics(),
            "b": _setup_metrics(
                completion=0.60, ttfmu=8.0, app_install=0.75,
                abandonment=0.10, firmware_tolerance=6.0,
                assembly_tolerance=1.8, pairing_tolerance=1.2,
            ),
            "c": _setup_metrics(
                completion=0.40, ttfmu=13.0, app_install=0.30,
                abandonment=0.20, firmware_tolerance=4.0,
                assembly_tolerance=1.5, pairing_tolerance=1.2,
            ),
        },
        weights={"a": 0.5, "b": 0.3, "c": 0.2},
        product_type="wearable",
        requires_companion_app=True,
        flags={
            "c": ["tier3_setup_risk", "setup_critical", "guide_printed"],
        },
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "wearable"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_ACCEPTABLE
    assert out.setup_experience_index == 0.7243
    assert out.weighted_oob_setup_completion_rate == 0.71
    assert out.weighted_time_to_first_meaningful_use_min == 7.0
    assert out.weighted_companion_app_install_rate == 0.585
    assert out.weighted_account_creation_abandonment == 0.09
    assert out.weighted_firmware_update_tolerance_min == 7.1
    assert out.weighted_physical_assembly_tolerance == 2.34
    assert out.weighted_pairing_friction_tolerance == 1.7
    assert [p.setup_tier for p in out.cluster_profiles] == [
        TIER_SEAMLESS,
        TIER_ROUGH,
        TIER_SLOW,
    ]
    assert out.seamless_share == 0.5
    assert out.rough_share == 0.3
    assert out.slow_share == 0.2
    assert out.blocked_share == 0.0
    assert out.primary_blocker == BLOCKER_COMPANION_APP
    assert out.primary_blocker_share == 0.7
    assert out.blocker_distribution[BLOCKER_COMPANION_APP] == 0.7
    assert out.blocker_distribution[BLOCKER_PAIRING] == 0.3
    assert sum(out.blocker_distribution.values()) == 1.0
    assert all(p.primary_blocker in VALID_BLOCKERS for p in out.cluster_profiles)
    assert len(out.levers) == 8
    assert all(lever.key in VALID_LEVERS for lever in out.levers)
    assert out.levers[0].key == LEVER_GUIDED_SETUP
    assert out.levers[0].opportunity_share == 0.5
    assert out.levers[1].key == LEVER_ONE_TAP_PAIRING
    assert out.levers[1].opportunity_share == 0.5
    assert out.levers[2].key == LEVER_PREFLASHED_FIRMWARE
    assert out.levers[2].opportunity_share == 0.5
    assert out.flags == ["tier3_setup_risk", "printed_guide_segment"]
    assert out.recommendations
    assert out.meta["primary_blocker_score"] == 0.496
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["requires_companion_app"] is True
    assert out.meta["thresholds"]["verdict_acceptable_index"] == 0.55


def test_blocked_cluster_produces_blocked_verdict() -> None:
    out = _build(
        specs={
            "a": _setup_metrics(
                completion=0.10, ttfmu=18.0, abandonment=0.30,
                firmware_tolerance=2.0, assembly_tolerance=1.0,
                pairing_tolerance=1.0,
            )
        },
        weights={"a": 1.0},
        product_type="consumer_hardware",
        flags={"a": ["setup_critical", "tier3_setup_risk"]},
    )

    assert out.verdict == VERDICT_BLOCKED
    assert out.setup_experience_index == 0.325
    assert out.blocked_share == 1.0
    assert out.primary_blocker == BLOCKER_TIME_TO_VALUE
    assert out.primary_blocker_share == 1.0
    assert out.cluster_profiles[0].setup_tier == TIER_BLOCKED
    assert out.cluster_profiles[0].architect_flags == [
        "setup_critical",
        "tier3_setup_risk",
    ]
    assert out.flags == [
        "blocked_setup_clusters",
        "setup_critical_market",
        "time_to_value_slow",
        "account_abandonment_market",
        "firmware_update_friction",
        "tier3_setup_risk",
    ]
    assert all(lever.opportunity_share == 1.0 for lever in out.levers[:6])
    assert out.levers[0].key == LEVER_ACCOUNT_OPTIONAL
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


def test_supported_product_type_with_missing_metrics_stays_supported() -> None:
    """``product_type_supported`` must reflect the run's product type,
    not whether metrics happened to be available: a supported hardware
    run with no per-cluster metrics is still a supported read, and the
    recommendation must say metrics are missing rather than claiming the
    run does not use the hardware stack."""
    out = _build(
        specs={"a": _setup_metrics(), "b": _setup_metrics()},
        weights={"a": 0.6, "b": 0.4},
        conductor_results={},
        product_type="consumer_hardware",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.levers == []
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 0
    assert "No per-cluster SetupFirstUseArchitect metrics" in out.recommendations[0]


def test_unsupported_product_type_ignores_stray_metrics() -> None:
    """An unsupported (non-hardware) product type must always return
    INSUFFICIENT_DATA, even if a mismatched caller supplies
    SetupFirstUseArchitect metrics: the support flag is product-type
    driven and stray metrics must not manufacture a FAST read for a run
    whose stack does not include SetupFirstUseArchitect."""
    out = _build(
        specs={"a": _setup_metrics(completion=0.95, ttfmu=3.5)},
        weights={"a": 1.0},
        product_type="saas",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.levers == []
    assert out.flags == []
    assert out.meta["product_type_supported"] is False
    assert out.meta["covered_clusters"] == 0
    assert "does not use that stack" in out.recommendations[0]


def test_saas_product_type_is_insufficient() -> None:
    out = _build(product_type="saas", conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.meta["covered_clusters"] == 0


def test_zero_weight_clusters_are_excluded() -> None:
    specs = {
        "a": _setup_metrics(
            completion=0.95, ttfmu=3.5, abandonment=0.02,
            firmware_tolerance=9.5,
        ),
        "zero": _setup_metrics(
            completion=0.10, ttfmu=19.0, abandonment=0.30,
            firmware_tolerance=2.0,
        ),
    }
    out = _build(
        specs=specs,
        weights={"a": 1.0, "zero": 0.0},
        product_type="b2b_hardware",
    )

    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "a"
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 1.0
    assert out.verdict == VERDICT_FAST


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={"a": {"oob_setup_completion_rate": 0.90}},
        weights={"a": 1.0},
        product_type="consumer_hardware",
    )

    profile = out.cluster_profiles[0]
    assert profile.oob_setup_completion_rate == 0.9
    assert profile.companion_app_install_rate == 0.7
    assert profile.account_creation_abandonment == 0.05
    assert profile.firmware_update_tolerance_min == 8.0
    assert profile.physical_assembly_tolerance == 2.75
    assert profile.pairing_friction_tolerance == 2.5
    assert profile.time_to_first_meaningful_use_min == 6.0
    assert profile.initial_customisation_depth == 0.3
    assert profile.setup_experience_index == 0.9
    assert profile.setup_tier == TIER_SEAMLESS
    assert out.verdict == VERDICT_FAST


def test_partial_metrics_do_not_manufacture_levers_or_flags() -> None:
    """A payload missing most fields must stay friction-neutral: the
    neutral defaults sit below every lever/flag trigger, so the read
    never invents an onboarding wizard, a firmware blocker, or a
    printed-guide segment from absent data."""
    out = _build(
        specs={"a": {"oob_setup_completion_rate": 0.90}},
        weights={"a": 1.0},
        product_type="consumer_hardware",
    )

    assert out.flags == []
    lever_shares = {lever.key: lever.opportunity_share for lever in out.levers}
    assert lever_shares[LEVER_GUIDED_SETUP] == 0.0
    assert lever_shares[LEVER_ONBOARDING_WIZARD] == 0.0
    assert lever_shares[LEVER_COMPANION_APP] == 0.0
    assert lever_shares[LEVER_ACCOUNT_OPTIONAL] == 0.0
    assert lever_shares[LEVER_PREFLASHED_FIRMWARE] == 0.0
    assert lever_shares[LEVER_SIMPLIFIED_ASSEMBLY] == 0.0
    assert lever_shares[LEVER_ONE_TAP_PAIRING] == 0.0
    assert lever_shares[LEVER_PRINTED_GUIDE] == 0.0
    assert out.weighted_oob_setup_completion_rate == 0.9
    assert out.weighted_time_to_first_meaningful_use_min == 6.0


def test_malformed_results_are_tolerated() -> None:
    out = _build(
        specs={"a": _setup_metrics()},
        weights={"a": 1.0},
        results='{"product_type_detected": "iot_hardware"}',
        product_type="iot_hardware",
    )
    assert out.product_type == "iot_hardware"
    assert out.verdict != VERDICT_INSUFFICIENT

    out_none = _build(
        specs={"a": _setup_metrics()},
        weights={"a": 1.0},
        results=None,
        conductor_results={},
    )
    assert out_none.product_type == "saas"
    assert out_none.verdict == VERDICT_INSUFFICIENT


def test_blocker_distribution_sums_to_one_and_is_stable() -> None:
    specs = {
        "setup_cluster": _setup_metrics(
            completion=0.55, ttfmu=4.0,
        ),
        "ttfmu_cluster": _setup_metrics(
            completion=0.95, ttfmu=15.0,
        ),
        "firmware_cluster": _setup_metrics(
            completion=0.95, ttfmu=4.0,
            firmware_tolerance=2.0,
        ),
    }
    out = _build(
        specs=specs,
        weights={
            "setup_cluster": 0.5,
            "ttfmu_cluster": 0.3,
            "firmware_cluster": 0.2,
        },
        product_type="health_hardware",
    )

    assert out.cluster_profiles[0].primary_blocker == BLOCKER_SETUP_COMPLETION
    assert out.cluster_profiles[1].primary_blocker == BLOCKER_TIME_TO_VALUE
    assert out.cluster_profiles[2].primary_blocker == BLOCKER_FIRMWARE_UPDATE
    assert sum(out.blocker_distribution.values()) == 1.0
    assert out.primary_blocker == BLOCKER_SETUP_COMPLETION
    assert out.primary_blocker_share == 0.5
    assert set(out.blocker_distribution) == set(BLOCKER_ORDER)


def test_ties_resolve_to_setup_completion() -> None:
    # Every severity is exactly 0.30: the read must point at the first
    # blocker in BLOCKER_ORDER (setup completion) instead of an
    # arbitrary one.
    out = _build(
        specs={
            "a": _setup_metrics(
                completion=0.70, ttfmu=7.5, app_install=0.70,
                abandonment=0.30, firmware_tolerance=7.0,
                assembly_tolerance=1.75, pairing_tolerance=1.75,
            )
        },
        weights={"a": 1.0},
        product_type="consumer_hardware",
        requires_companion_app=True,
    )

    assert out.primary_blocker == BLOCKER_SETUP_COMPLETION
    assert out.cluster_profiles[0].primary_blocker == BLOCKER_SETUP_COMPLETION
    assert out.cluster_profiles[0].primary_blocker_score == 0.3


def test_companion_app_friction_respects_brief() -> None:
    """Companion-app friction must only count when the founder's brief
    requires a companion app; otherwise the read would manufacture an
    app-install blocker for app-less products (the architect reports an
    install rate even when no app exists)."""
    specs = {
        "a": _setup_metrics(
            completion=0.95, ttfmu=4.0, app_install=0.20,
            abandonment=0.04, firmware_tolerance=9.5,
            assembly_tolerance=3.0, pairing_tolerance=2.4,
        )
    }
    out_false = _build(
        specs=specs,
        weights={"a": 1.0},
        product_type="wearable",
        requires_companion_app=False,
    )

    assert out_false.blocker_distribution[BLOCKER_COMPANION_APP] == 0.0
    assert out_false.primary_blocker == BLOCKER_TIME_TO_VALUE
    assert "companion_app_gap" not in out_false.flags
    assert out_false.meta["requires_companion_app"] is False
    lever_shares = {
        lever.key: lever.opportunity_share for lever in out_false.levers
    }
    assert lever_shares[LEVER_COMPANION_APP] == 0.0

    out_true = _build(
        specs=specs,
        weights={"a": 1.0},
        product_type="wearable",
        requires_companion_app=True,
    )

    assert out_true.primary_blocker == BLOCKER_COMPANION_APP
    assert out_true.blocker_distribution[BLOCKER_COMPANION_APP] == 1.0
    assert "companion_app_gap" in out_true.flags
    assert out_true.meta["requires_companion_app"] is True
    lever_shares = {
        lever.key: lever.opportunity_share for lever in out_true.levers
    }
    assert lever_shares[LEVER_COMPANION_APP] == 1.0


def test_index_and_tier_helpers_are_clamped() -> None:
    assert _setup_index({key: 0.0 for key in BLOCKER_ORDER}) == 1.0
    assert _setup_index({key: 1.0 for key in BLOCKER_ORDER}) < 1e-9
    assert _setup_tier(0.80) == TIER_SEAMLESS
    assert _setup_tier(0.60) == TIER_ROUGH
    assert _setup_tier(0.45) == TIER_SLOW
    assert _setup_tier(0.20) == TIER_BLOCKED


def test_architect_hardware_activation_is_real() -> None:
    """consumer_hardware is a supported product type: SetupFirstUseArchitect
    must actually run in the conductor stack for it."""
    result = Conductor().run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[{"text": "companion app required for setup"}],
        product_type=ProductType.CONSUMER_HARDWARE,
    )
    first_cluster = next(iter(result.cluster_results.values()))
    assert "SetupFirstUseArchitect" in first_cluster
    assert all(
        "SetupFirstUseArchitect" in cluster_outputs
        for cluster_outputs in result.cluster_results.values()
    )
    assert all(
        cluster_outputs["SetupFirstUseArchitect"].metrics[
            "oob_setup_completion_rate"
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
    out = build_setup_friction(
        {"product_type_detected": "consumer_hardware"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type="consumer_hardware",
        requires_companion_app=True,
    )

    assert out.verdict != VERDICT_INSUFFICIENT
    assert out.verdict in {
        VERDICT_FAST,
        VERDICT_ACCEPTABLE,
        VERDICT_SLOW,
        VERDICT_BLOCKED,
    }
    assert 0.0 <= out.setup_experience_index <= 1.0
    assert len(out.cluster_profiles) == len(registry)
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == out.meta["total_clusters"]
    assert out.meta["covered_weight"] > 0.9
    assert len(out.levers) == 8
    assert out.recommendations


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
        assumptions=[{"text": "companion app required for setup"}],
        product_type=ProductType.CONSUMER_HARDWARE,
    )

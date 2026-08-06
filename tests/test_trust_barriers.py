"""
Tests for the pure trust-barriers builder
(``app.simulation.trust_barriers``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.trust_barriers import (
    BARRIER_BRAND,
    BARRIER_COMMUNITY,
    BARRIER_RECOVERY,
    BARRIER_SECURITY,
    BARRIER_SOCIAL_PROOF,
    TIER_CRITICAL,
    TIER_HIGH,
    TIER_LOW,
    TIER_MODERATE,
    VALID_BARRIERS,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_CRITICAL,
    VERDICT_HIGH,
    VERDICT_INSUFFICIENT,
    VERDICT_LOW_BARRIER,
    VERDICT_MODERATE,
    TrustBarriersOut,
)
from app.simulation.trust_barriers import (
    BARRIER_ORDER,
    build_trust_barriers,
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


def _trust_metrics(
    *,
    brand: float = 0.70,
    spf: float = 0.60,
    security: float = 0.10,
    decay: float = 0.10,
    recovery: float = 21.0,
    community: float = 0.20,
    press: float = 0.10,
    free_trial: float = 0.30,
    threshold: float = 30.0,
    founder: float = 0.30,
) -> dict[str, float]:
    return {
        "brand_deficit_multiplier": brand,
        "social_proof_met_fraction": spf,
        "security_concern_intensity": security,
        "trust_decay_rate_per_incident": decay,
        "trust_recovery_days": recovery,
        "community_size_signal_weight": community,
        "press_mention_lift": press,
        "free_trial_as_trust_substitute": free_trial,
        "social_proof_threshold": threshold,
        "founder_vs_product_credibility": founder,
    }


def _conductor(specs: dict[str, dict[str, float]]) -> dict[str, Any]:
    return {
        cid: {
            "TrustArchitect": {
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
) -> TrustBarriersOut:
    specs = specs or {
        "a": _trust_metrics(),
        "b": _trust_metrics(),
        "c": _trust_metrics(),
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
    return build_trust_barriers(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_low_barrier_payload() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.95, spf=0.95, security=0.05,
                decay=0.05, recovery=14.0, community=0.40,
                press=0.20, free_trial=0.10, threshold=40.0,
            ),
            "b": _trust_metrics(
                brand=0.90, spf=0.90, security=0.05,
                decay=0.05, recovery=14.0, community=0.40,
                press=0.20, free_trial=0.10, threshold=40.0,
            ),
            "c": _trust_metrics(
                brand=0.85, spf=0.85, security=0.03,
                decay=0.03, recovery=14.0, community=0.40,
                press=0.20, free_trial=0.10, threshold=40.0,
            ),
        },
        weights={"a": 0.4, "b": 0.4, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_LOW_BARRIER
    assert out.trust_index == 0.7914
    assert out.weighted_brand_deficit_multiplier == 0.91
    assert out.weighted_social_proof_met_fraction == 0.91
    assert out.low_share == 0.8
    assert out.moderate_share == 0.2
    assert out.high_share == 0.0
    assert out.critical_share == 0.0
    assert len(out.cluster_profiles) == 3
    assert all(p.barrier_tier in VALID_TIERS for p in out.cluster_profiles)
    assert out.cluster_profiles[0].barrier_tier == TIER_LOW
    assert out.cluster_profiles[1].barrier_tier == TIER_LOW
    assert out.cluster_profiles[2].barrier_tier == TIER_MODERATE
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True
    assert len(out.levers) == 6
    assert [lever.opportunity_share for lever in out.levers] == sorted(
        [lever.opportunity_share for lever in out.levers], reverse=True
    )
    assert "brand_deficit_critical" not in out.flags
    assert "critical_trust_clusters" not in out.flags
    assert out.recommendations
    assert sum(out.barrier_distribution.values()) > 0.99
    assert out.primary_barrier in VALID_BARRIERS


def test_moderate_verdict_from_critical_minority() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.95, spf=0.95, security=0.05, decay=0.05,
            ),
            "b": _trust_metrics(
                brand=0.35, spf=0.35, security=0.10, decay=0.10,
            ),
        },
        weights={"a": 0.6, "b": 0.4},
    )

    assert out.verdict == VERDICT_MODERATE
    assert out.critical_share == 0.4
    assert "critical_trust_clusters" in out.flags
    assert out.trust_index == 0.5590


def test_critical_verdict_when_whole_market_untrusted() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.30, spf=0.30, security=0.20, decay=0.20,
            ),
            "b": _trust_metrics(
                brand=0.25, spf=0.25, security=0.20, decay=0.20,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_CRITICAL
    assert out.critical_share == 1.0
    assert out.trust_index < 0.35
    assert "critical_trust_clusters" in out.flags
    assert "brand_deficit_critical" in out.flags
    assert "social_proof_missing" in out.flags
    assert all(p.barrier_tier == TIER_CRITICAL for p in out.cluster_profiles)


def test_primary_barrier_attribution_and_distribution() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.30, spf=0.90, security=0.05, recovery=10.0,
                community=0.40,
            ),
            "b": _trust_metrics(
                brand=0.90, spf=0.10, security=0.05, recovery=10.0,
                community=0.40,
            ),
            "c": _trust_metrics(
                brand=0.90, spf=0.90, security=0.40, recovery=10.0,
                community=0.40,
            ),
        },
        weights={"a": 0.4, "b": 0.4, "c": 0.2},
    )

    assert out.cluster_profiles[0].primary_barrier == BARRIER_BRAND
    assert out.cluster_profiles[1].primary_barrier == BARRIER_SOCIAL_PROOF
    assert out.cluster_profiles[2].primary_barrier == BARRIER_SECURITY
    assert out.primary_barrier == BARRIER_BRAND  # tie-break by BARRIER_ORDER
    assert out.primary_barrier_label == "Brand deficit"
    assert out.primary_barrier_share == 0.4
    assert out.barrier_distribution[BARRIER_BRAND] == 0.4
    assert out.barrier_distribution[BARRIER_SOCIAL_PROOF] == 0.4
    assert out.barrier_distribution[BARRIER_SECURITY] == 0.2
    assert sum(out.barrier_distribution.values()) == 1.0
    assert any("Brand deficit" in r for r in out.recommendations)


def test_levers_apply_to_market_with_objection() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.30, spf=0.10, security=0.30,
                decay=0.30, recovery=60.0, community=0.0,
                free_trial=0.70,
            ),
        },
        weights={"a": 1.0},
    )

    by_key = {lever.key: lever for lever in out.levers}
    assert by_key["social_proof_building"].opportunity_share == 1.0
    assert by_key["risk_free_trial"].opportunity_share == 1.0
    assert by_key["brand_credibility"].opportunity_share == 1.0
    assert by_key["security_assurances"].opportunity_share == 1.0
    assert by_key["community_signals"].opportunity_share == 1.0
    assert by_key["incident_response"].opportunity_share == 1.0
    assert "100%" in by_key["social_proof_building"].action


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={
            "a": {"social_proof_threshold": 40.0},
            "b": {"social_proof_threshold": 40.0},
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.weighted_brand_deficit_multiplier == 0.70
    assert out.weighted_social_proof_met_fraction == 0.60
    assert out.weighted_security_concern_intensity == 0.10
    assert out.weighted_trust_decay_rate == 0.10
    assert out.weighted_trust_recovery_days == 21.0
    assert out.weighted_community_signal_weight == 0.20
    assert out.weighted_press_mention_lift == 0.10
    assert out.weighted_free_trial_substitute == 0.30
    assert out.verdict == VERDICT_HIGH
    assert all(p.barrier_tier == TIER_HIGH for p in out.cluster_profiles)
    assert "critical_trust_clusters" not in out.flags
    assert out.primary_barrier == BARRIER_COMMUNITY


def test_entirely_empty_metric_blocks_are_skipped() -> None:
    out = _build(
        specs={"a": {}, "b": {}},
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations


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
                "a": _trust_metrics(),
                "b": _trust_metrics(),
            },
            weights={"a": 0.5, "b": 0.5},
            product_type=product_type,
        )
        assert out.verdict != VERDICT_INSUFFICIENT
        assert out.meta["product_type_supported"] is True
        assert out.product_type == product_type


def test_registry_entries_without_metrics_are_skipped() -> None:
    out = _build(
        specs={"a": _trust_metrics()},
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
                    "population_weight": 0.5,
                },
            ]
        ),
        conductor_results=_conductor(
            {"a": _trust_metrics()}
        ),
    )

    assert out.meta["total_clusters"] == 2
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 0.5
    assert len(out.cluster_profiles) == 1


def test_barrier_order_is_exported_and_complete() -> None:
    assert BARRIER_ORDER[0] == BARRIER_BRAND
    assert set(BARRIER_ORDER) == set(VALID_BARRIERS)
    assert len(BARRIER_ORDER) == 6


def test_recovery_barrier_can_be_primary() -> None:
    out = _build(
        specs={
            "a": _trust_metrics(
                brand=0.90, spf=0.90, security=0.05,
                decay=0.05, recovery=90.0, community=0.40,
            ),
        },
        weights={"a": 1.0},
    )

    assert out.cluster_profiles[0].primary_barrier == BARRIER_RECOVERY
    assert out.cluster_profiles[0].primary_barrier_score == 1.0
    assert out.primary_barrier == BARRIER_RECOVERY

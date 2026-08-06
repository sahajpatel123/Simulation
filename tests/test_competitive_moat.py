"""
Tests for the pure competitive-moat builder
(``app.simulation.competitive_moat``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.competitive_moat import (
    LEVER_DISTRIBUTION,
    LEVER_FEATURE_PARITY,
    LEVER_PRICING_POWER,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    VERDICT_STRONG,
    VERDICT_WEAK,
    CompetitiveMoatOut,
)
from app.simulation.architects.competitive_dynamics import (
    CompetitiveDynamicsArchitect,
)
from app.simulation.competitive_moat import (
    COMPETITIVE_MOAT_PRODUCT_TYPES,
    LEVER_ORDER,
    build_competitive_moat,
)
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import ARCHITECT_STACKS, Conductor
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


def _metrics(
    *,
    feature_parity: float = 1.0,
    brand_deficit: float = 1.0,
    will_pay: float = 0.9,
    dist_access: float = 1.0,
    loss_aversion: float = 0.9,
    displacement: float = 45.0,
    loyalty: float = 0.4,
) -> dict[str, Any]:
    return {
        "comp": {
            "feature_parity_met": feature_parity,
            "loss_aversion_magnitude": loss_aversion,
            "competitive_displacement_days": displacement,
            "competitor_brand_loyalty_strength": loyalty,
        },
        "trust": {"brand_deficit_multiplier": brand_deficit},
        "pricing": {"will_pay_probability": will_pay},
        "dist": {"distribution_accessibility_multiplier": dist_access},
    }


def _low_metrics() -> dict[str, Any]:
    return _metrics(
        feature_parity=0.0,
        brand_deficit=0.2,
        will_pay=0.2,
        dist_access=0.2,
        loss_aversion=0.2,
    )


def _mid_metrics() -> dict[str, Any]:
    return _metrics(
        feature_parity=0.6,
        brand_deficit=0.5,
        will_pay=0.4,
        dist_access=0.5,
        loss_aversion=0.5,
    )


def _conductor(specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cid, blocks in specs.items():
        cluster_block: dict[str, Any] = {}
        if "comp" in blocks:
            cluster_block["CompetitiveDynamicsArchitect"] = {
                "metrics": blocks["comp"],
                "flags": blocks.get("comp_flags", {}),
            }
        if "trust" in blocks:
            cluster_block["TrustArchitect"] = {
                "metrics": blocks["trust"],
                "flags": blocks.get("trust_flags", {}),
            }
        if "pricing" in blocks:
            cluster_block["PricingArchitect"] = {
                "metrics": blocks["pricing"],
                "flags": blocks.get("pricing_flags", {}),
            }
        if "dist" in blocks:
            cluster_block["DistributionChannelArchitect"] = {
                "metrics": blocks["dist"],
                "flags": blocks.get("dist_flags", {}),
            }
        result[cid] = cluster_block
    return result


def _build(
    *,
    specs: dict[str, dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
    conductor_results: dict[str, Any] | None = None,
    registry: list[dict[str, Any]] | None = None,
    product_type: str = "saas",
) -> CompetitiveMoatOut:
    specs = specs or {
        "a": _metrics(),
        "b": _metrics(),
        "c": _metrics(),
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
    return build_competitive_moat(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_strong_payload() -> None:
    out = _build()

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_STRONG
    assert out.moat_index == 0.96
    assert out.weighted_feature_parity == 1.0
    assert out.weighted_brand_trust == 1.0
    assert out.weighted_pricing_power == 0.9
    assert out.weighted_distribution_reach == 1.0
    assert out.weighted_switching_lock_in == 0.9
    assert out.strong_share == 1.0
    assert out.moderate_share == 0.0
    assert out.weak_share == 0.0
    assert out.primary_weakest_lever == LEVER_PRICING_POWER
    assert out.primary_weakest_lever_label == "Pricing power"
    assert out.primary_weakest_lever_share == 1.0
    assert out.lever_distribution[LEVER_PRICING_POWER] == 1.0
    assert sum(out.lever_distribution.values()) == 1.0
    assert len(out.cluster_profiles) == 3
    assert all(p.moat_tier in VALID_TIERS for p in out.cluster_profiles)
    assert all(p.moat_tier == TIER_STRONG for p in out.cluster_profiles)
    assert all(p.weakest_lever == LEVER_PRICING_POWER for p in out.cluster_profiles)
    assert len(out.top_protected) == 3
    assert len(out.top_vulnerable) == 3
    assert "feature_parity_gap" not in out.flags
    assert "vacant_category" not in out.flags
    assert "incumbent_loyalty_entrenched" not in out.flags
    assert out.recommendations
    assert "pricing power" in out.recommendations[0].lower()
    assert any("strong across" in r.lower() for r in out.recommendations)
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True
    assert out.meta["levers_available"][LEVER_DISTRIBUTION] is True


def test_weak_verdict_from_whole_market_weak() -> None:
    out = _build(
        specs={
            "a": _low_metrics(),
            "b": _low_metrics(),
            "c": _low_metrics(),
        }
    )

    assert out.verdict == VERDICT_WEAK
    assert out.moat_index == 0.15
    assert out.weak_share == 1.0
    assert out.strong_share == 0.0
    assert out.primary_weakest_lever == LEVER_FEATURE_PARITY
    assert "feature_parity_gap" in out.flags
    assert "brand_trust_gap" in out.flags
    assert "pricing_power_gap" in out.flags
    assert "distribution_gap" in out.flags
    assert "switching_lock_in_gap" in out.flags
    assert "weak_moat_concentration" in out.flags
    assert all(p.moat_tier == TIER_WEAK for p in out.cluster_profiles)
    assert out.recommendations
    assert "feature parity" in out.recommendations[0].lower()


def test_moderate_verdict_from_mid_market() -> None:
    out = _build(
        specs={
            "a": _mid_metrics(),
            "b": _mid_metrics(),
            "c": _mid_metrics(),
        }
    )

    assert out.verdict == VERDICT_MODERATE
    assert out.moat_index == 0.51
    assert all(p.moat_tier == TIER_MODERATE for p in out.cluster_profiles)


def test_missing_competitive_metrics_returns_insufficient() -> None:
    out = build_competitive_moat(
        {"product_type_detected": "saas"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results={},
        cluster_registry=_registry(
            [
                {
                    "cluster_id": "a",
                    "name": "A",
                    "population_weight": 0.5,
                }
            ]
        ),
        product_type="saas",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.moat_index == 0.0
    assert out.cluster_profiles == []
    assert out.meta["total_clusters"] == 1
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations
    assert "no per-cluster" in out.recommendations[0].lower()


def test_zero_weight_clusters_are_excluded() -> None:
    out = _build(
        specs={
            "a": _metrics(),
            "b": _metrics(),
        },
        weights={"a": 0.6, "b": 0.0},
    )

    assert out.meta["total_clusters"] == 2
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 0.6
    assert [p.cluster_id for p in out.cluster_profiles] == ["a"]
    assert out.strong_share == 1.0


def test_weights_renormalize_when_distribution_unavailable() -> None:
    specs = {
        "a": {
            "comp": {
                "feature_parity_met": 1.0,
                "loss_aversion_magnitude": 0.9,
            },
            "trust": {"brand_deficit_multiplier": 1.0},
            "pricing": {"will_pay_probability": 0.9},
        },
        "b": {
            "comp": {
                "feature_parity_met": 1.0,
                "loss_aversion_magnitude": 0.9,
            },
            "trust": {"brand_deficit_multiplier": 1.0},
            "pricing": {"will_pay_probability": 0.9},
        },
    }
    out = _build(specs=specs)

    # 0.25*1 + 0.20*1 + 0.15*0.9 + 0.25*0.9 = 0.81, renormalized by 0.85.
    assert out.moat_index == 0.9529
    assert out.meta["levers_available"][LEVER_DISTRIBUTION] is False
    assert out.weighted_distribution_reach == 0.0
    assert out.verdict == VERDICT_STRONG


def test_missing_fields_use_neutral_defaults() -> None:
    specs = {
        "a": {
            "comp": {"competitor_brand_loyalty_strength": 0.6},
            "trust": {"social_proof_met_fraction": 1.0},
            "pricing": {"price_ceiling": 2000.0},
            "dist": {"online_preference": 0.8},
        }
    }
    out = _build(specs=specs, weights={"a": 1.0})

    assert out.moat_index == 0.5
    assert out.verdict == VERDICT_MODERATE
    assert out.weighted_feature_parity == 0.5
    assert out.weighted_brand_trust == 0.5
    assert out.weighted_pricing_power == 0.5
    assert out.weighted_distribution_reach == 0.5
    assert out.weighted_switching_lock_in == 0.5
    assert "feature_parity_gap" not in out.flags
    assert "incumbent_loyalty_entrenched" in out.flags
    assert out.cluster_profiles[0].displacement_days == 45
    assert out.primary_weakest_lever == LEVER_FEATURE_PARITY


def test_weakest_lever_tie_breaks_by_order() -> None:
    specs = {
        "a": _metrics(
            feature_parity=0.3,
            brand_deficit=0.3,
            will_pay=0.9,
            dist_access=0.9,
            loss_aversion=0.9,
        )
    }
    out = _build(specs=specs, weights={"a": 1.0})

    assert out.primary_weakest_lever == LEVER_FEATURE_PARITY
    assert out.cluster_profiles[0].weakest_lever == LEVER_FEATURE_PARITY
    assert out.lever_distribution[LEVER_FEATURE_PARITY] == 1.0


def test_top_protected_and_vulnerable_ordering() -> None:
    specs = {
        "a": _metrics(),
        "b": _mid_metrics(),
        "c": _low_metrics(),
    }
    out = _build(specs=specs, weights={"a": 0.2, "b": 0.3, "c": 0.5})

    assert [p.cluster_id for p in out.top_protected] == ["a", "b", "c"]
    assert [p.cluster_id for p in out.top_vulnerable] == ["c", "b", "a"]


def test_top_lists_tie_break_by_population_weight() -> None:
    specs = {
        "a": _metrics(),
        "b": _metrics(),
    }
    out = _build(specs=specs, weights={"a": 0.2, "b": 0.8})

    assert out.top_protected[0].cluster_id == "b"
    assert out.top_vulnerable[0].cluster_id == "b"
    assert out.top_vulnerable[1].cluster_id == "a"


def test_vacant_category_and_free_competitor_flags() -> None:
    vacant = {
        cid: {
            **_metrics(),
            "comp_flags": {"no_competition": True},
        }
        for cid in ("a", "b", "c")
    }
    out = _build(specs=vacant)
    assert "vacant_category" in out.flags
    assert out.meta["no_competition_share"] == 1.0
    assert any("no incumbent" in r.lower() for r in out.recommendations)

    free = {
        cid: {
            **_metrics(),
            "comp_flags": {"free_competitor_present": True},
        }
        for cid in ("a", "b", "c")
    }
    out = _build(specs=free)
    assert "free_competitor_present" in out.flags
    assert out.meta["free_competitor_share"] == 1.0
    assert any("free alternatives" in r.lower() for r in out.recommendations)


def test_strong_verdict_withheld_when_weak_share_high() -> None:
    specs = {
        "a": _metrics(),
        "b": _low_metrics(),
        "c": _low_metrics(),
    }
    out = _build(specs=specs, weights={"a": 0.5, "b": 0.25, "c": 0.25})

    # 0.5*0.96 + 0.25*0.15 + 0.25*0.15 = 0.555 -> above MODERATE, below
    # STRONG; weak share is 0.5 so the strong guard would also withhold.
    assert out.moat_index == 0.555
    assert out.weak_share == 0.5
    assert out.verdict == VERDICT_MODERATE


def test_displacement_days_are_clamped() -> None:
    specs = {
        "a": _metrics(displacement=9999.0),
        "b": _metrics(displacement=0.0),
    }
    out = _build(specs=specs, weights={"a": 0.5, "b": 0.5})

    by_id = {p.cluster_id: p for p in out.cluster_profiles}
    assert by_id["a"].displacement_days == 365
    assert by_id["b"].displacement_days == 1


def test_product_type_from_results_fallback() -> None:
    out = build_competitive_moat(
        {"product_type_detected": "iot_hardware"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=_conductor({"a": _metrics()}),
        cluster_registry=_registry(
            [
                {
                    "cluster_id": "a",
                    "name": "A",
                    "population_weight": 1.0,
                }
            ]
        ),
        product_type="iot_hardware",
    )

    assert out.product_type == "iot_hardware"
    assert out.verdict != VERDICT_INSUFFICIENT
    assert out.meta["levers_available"][LEVER_DISTRIBUTION] is True


def test_all_product_types_are_supported() -> None:
    for product_type in sorted(COMPETITIVE_MOAT_PRODUCT_TYPES):
        out = _build(
            specs={"a": _metrics()},
            weights={"a": 1.0},
            product_type=product_type,
        )

        assert out.verdict != VERDICT_INSUFFICIENT
        assert out.meta["product_type_supported"] is True
        assert out.product_type == product_type
        assert out.meta["levers_available"][LEVER_FEATURE_PARITY] is True


def test_unsupported_product_type_returns_insufficient() -> None:
    out = build_competitive_moat(
        {"product_type_detected": "hovercraft"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        conductor_results=_conductor({"a": _metrics()}),
        cluster_registry=_registry(
            [
                {
                    "cluster_id": "a",
                    "name": "A",
                    "population_weight": 1.0,
                }
            ]
        ),
        product_type="hovercraft",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.cluster_profiles == []
    assert any("not modeled" in r.lower() for r in out.recommendations)


def test_supported_set_matches_conductor_activation() -> None:
    """Every advertised product type must actually run the moat's core
    architect, or the read would claim support and return no data.
    """
    arch = CompetitiveDynamicsArchitect()
    activated = {
        pt.value
        for pt, stack in ARCHITECT_STACKS.items()
        if "CompetitiveDynamicsArchitect" in stack
        and (pt.value in arch.product_types or len(arch.product_types) == 0)
    }

    assert activated == {pt.value for pt in ProductType}
    assert COMPETITIVE_MOAT_PRODUCT_TYPES == activated


def test_real_conductor_runs_moat_metrics_for_newer_product_types() -> None:
    """End-to-end guard: the newer enum product types used to return
    INSUFFICIENT_DATA because CompetitiveDynamicsArchitect never ran in
    their conductor stack.
    """
    conductor = Conductor()
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in ClusterRegistry().all_clusters()
    ]

    for product_type in (ProductType.SMART_HOME, ProductType.CONSUMER_APP):
        result = conductor.run(
            agents=[],
            env_params={},
            assumptions=[],
            product_type=product_type,
        )
        first = next(iter(result.cluster_results.values()))
        assert "CompetitiveDynamicsArchitect" in first

        conductor_results = {
            cid: {
                name: {"metrics": output.metrics, "flags": output.flags}
                for name, output in arch_outputs.items()
            }
            for cid, arch_outputs in result.cluster_results.items()
        }
        out = build_competitive_moat(
            {"product_type_detected": product_type.value},
            simulation_id=7,
            project_id=10,
            status="COMPLETED",
            conductor_results=conductor_results,
            cluster_registry=registry,
            product_type=product_type.value,
        )

        assert out.verdict != VERDICT_INSUFFICIENT
        assert out.meta["product_type_supported"] is True
        assert out.meta["covered_clusters"] == 52
        assert out.meta["levers_available"][LEVER_FEATURE_PARITY] is True

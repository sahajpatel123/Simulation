"""
Tests for the pure cultural-fit builder
(``app.simulation.cultural_fit``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.cultural_fit import (
    BARRIER_ALIGNMENT,
    BARRIER_FAMILY,
    BARRIER_GEO,
    BARRIER_LANGUAGE,
    BARRIER_RELIGIOUS,
    BARRIER_SEASONAL,
    CulturalFitOut,
    LEVER_COMPLIANCE,
    LEVER_FAMILY,
    LEVER_GEO,
    LEVER_LOCALIZATION,
    LEVER_MESSAGING,
    LEVER_SEASONAL,
    TIER_MISALIGNED,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VALID_BARRIERS,
    VALID_LEVERS,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_INSUFFICIENT,
    VERDICT_MISALIGNED,
    VERDICT_MODERATE_FIT,
    VERDICT_STRONG_FIT,
    VERDICT_WEAK_FIT,
)
from app.simulation.cultural_fit import (
    BARRIER_ORDER,
    _fit_index,
    _fit_tier,
    build_cultural_fit,
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


def _cultural_metrics(
    *,
    alignment: float = 0.60,
    language: float = 0.70,
    family: float = 0.45,
    seasonal: float = 0.65,
    brand: float = 0.50,
    religious: float = 0.20,
    geo: float = 0.75,
    correction: float = 1.0,
) -> dict[str, float]:
    return {
        "cultural_alignment_score": alignment,
        "language_accessibility_score": language,
        "family_influence_factor": family,
        "seasonal_relevance_score": seasonal,
        "local_brand_trust": brand,
        "religious_sensitivity_risk": religious,
        "geo_target_alignment": geo,
        "overall_cultural_correction": correction,
    }


def _conductor(
    specs: dict[str, dict[str, Any]],
    flags: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = flags or {}
    return {
        cid: {
            "CulturalContextArchitect": {
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
) -> CulturalFitOut:
    specs = specs or {
        "a": _cultural_metrics(),
        "b": _cultural_metrics(),
        "c": _cultural_metrics(),
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
    return build_cultural_fit(
        results if results is not None else {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_strong_fit_payload() -> None:
    out = _build(
        specs={
            "a": _cultural_metrics(
                alignment=0.90, language=0.90, family=0.20,
                seasonal=0.80, brand=0.70, religious=0.10,
                geo=0.90, correction=1.05,
            ),
            "b": _cultural_metrics(
                alignment=0.85, language=0.85, family=0.25,
                seasonal=0.75, brand=0.60, religious=0.15,
                geo=0.85,
            ),
            "c": _cultural_metrics(
                alignment=0.70, language=0.80, family=0.40,
                seasonal=0.70, brand=0.50, religious=0.20,
                geo=0.80,
            ),
        },
        weights={"a": 0.5, "b": 0.3, "c": 0.2},
    )

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict == VERDICT_STRONG_FIT
    assert out.fit_index == 0.832
    assert out.weighted_language_accessibility == 0.865
    assert out.weighted_cultural_alignment == 0.845
    assert out.weighted_family_influence == 0.255
    assert out.weighted_seasonal_relevance == 0.765
    assert out.weighted_local_brand_trust == 0.63
    assert out.weighted_religious_risk == 0.135
    assert out.weighted_geo_alignment == 0.865
    assert out.weighted_cultural_correction == 1.025
    assert out.strong_share == 0.8
    assert out.moderate_share == 0.2
    assert out.weak_share == 0.0
    assert out.misaligned_share == 0.0
    assert out.primary_barrier == BARRIER_FAMILY
    assert out.primary_barrier_share == 1.0
    assert out.barrier_distribution[BARRIER_FAMILY] == 1.0
    assert len(out.cluster_profiles) == 3
    assert [p.fit_tier for p in out.cluster_profiles] == [
        TIER_STRONG,
        TIER_STRONG,
        TIER_MODERATE,
    ]
    assert all(p.primary_barrier in VALID_BARRIERS for p in out.cluster_profiles)
    assert len(out.levers) == 6
    assert all(lever.key in VALID_LEVERS for lever in out.levers)
    assert out.levers[0].key == LEVER_GEO
    assert out.levers[0].opportunity_share == 0.2
    assert out.flags == []
    assert out.recommendations
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["primary_barrier_score"] == 0.255


def test_misaligned_cluster_produces_misaligned_verdict() -> None:
    out = _build(
        specs={
            "a": _cultural_metrics(
                alignment=0.20, language=0.30, family=0.80,
                seasonal=0.30, brand=0.20, religious=0.70,
                geo=0.40, correction=0.60,
            )
        },
        weights={"a": 1.0},
        flags={"a": ["language_barrier_detected", "religious_sensitivity_concern"]},
    )

    assert out.verdict == VERDICT_MISALIGNED
    assert out.fit_index == 0.265
    assert out.misaligned_share == 1.0
    assert out.primary_barrier == BARRIER_ALIGNMENT
    assert out.primary_barrier_share == 1.0
    assert out.cluster_profiles[0].fit_tier == TIER_MISALIGNED
    assert out.cluster_profiles[0].architect_flags == [
        "language_barrier_detected",
        "religious_sensitivity_concern",
    ]
    assert out.flags == [
        "misaligned_clusters",
        "language_barrier_market",
        "cultural_misalignment_market",
        "family_gatekeeper_market",
        "religious_sensitivity_market",
        "festival_timing_mismatch_market",
        "geo_mismatch_market",
    ]
    assert all(lever.opportunity_share == 1.0 for lever in out.levers)
    assert out.levers[0].key == LEVER_FAMILY
    assert "treat localization as a launch blocker" in out.recommendations[0]


def test_no_metrics_returns_insufficient_data() -> None:
    out = _build(conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.levers == []
    assert out.recommendations
    assert out.meta["covered_clusters"] == 0
    assert out.meta["covered_weight"] == 0.0
    assert out.meta["product_type_supported"] is False


def test_zero_weight_clusters_are_excluded() -> None:
    specs = {
        "a": _cultural_metrics(alignment=0.90, language=0.90, family=0.10),
        "zero": _cultural_metrics(alignment=0.10, language=0.10, family=0.90),
    }
    out = _build(
        specs=specs,
        weights={"a": 1.0, "zero": 0.0},
    )

    assert len(out.cluster_profiles) == 1
    assert out.cluster_profiles[0].cluster_id == "a"
    assert out.meta["covered_clusters"] == 1
    assert out.meta["covered_weight"] == 1.0
    assert out.verdict == VERDICT_STRONG_FIT


def test_missing_metrics_use_neutral_defaults() -> None:
    out = _build(
        specs={"a": {"cultural_alignment_score": 0.90}},
        weights={"a": 1.0},
    )

    profile = out.cluster_profiles[0]
    assert profile.language_accessibility_score == 0.7
    assert profile.family_influence_factor == 0.45
    assert profile.seasonal_relevance_score == 0.65
    assert profile.local_brand_trust == 0.5
    assert profile.religious_sensitivity_risk == 0.2
    assert profile.geo_target_alignment == 0.75
    assert profile.overall_cultural_correction == 1.0
    assert profile.cultural_fit_index == 0.74
    assert profile.fit_tier == TIER_MODERATE
    assert out.verdict == VERDICT_MODERATE_FIT


def test_malformed_results_are_tolerated() -> None:
    out = _build(
        specs={"a": _cultural_metrics()},
        weights={"a": 1.0},
        results='{"product_type_detected": "marketplace"}',
    )
    assert out.product_type == "marketplace"
    assert out.verdict != VERDICT_INSUFFICIENT

    out_none = _build(
        specs={"a": _cultural_metrics()},
        weights={"a": 1.0},
        results=None,
    )
    assert out_none.product_type == "saas"
    assert out_none.verdict != VERDICT_INSUFFICIENT


def test_barrier_distribution_sums_to_one_and_is_stable() -> None:
    specs = {
        "language_cluster": _cultural_metrics(
            language=0.30, alignment=0.80, family=0.30,
            religious=0.10, seasonal=0.80, geo=0.80,
        ),
        "family_cluster": _cultural_metrics(
            language=0.80, alignment=0.80, family=0.80,
            religious=0.10, seasonal=0.80, geo=0.80,
        ),
        "religious_cluster": _cultural_metrics(
            language=0.80, alignment=0.80, family=0.30,
            religious=0.70, seasonal=0.80, geo=0.80,
        ),
    }
    out = _build(
        specs=specs,
        weights={
            "language_cluster": 0.5,
            "family_cluster": 0.3,
            "religious_cluster": 0.2,
        },
    )

    assert out.cluster_profiles[0].primary_barrier == BARRIER_LANGUAGE
    assert out.cluster_profiles[1].primary_barrier == BARRIER_FAMILY
    assert out.cluster_profiles[2].primary_barrier == BARRIER_RELIGIOUS
    assert sum(out.barrier_distribution.values()) == 1.0
    assert out.primary_barrier == BARRIER_LANGUAGE
    assert out.primary_barrier_share == 0.5
    assert set(out.barrier_distribution) == set(BARRIER_ORDER)


def test_ties_resolve_to_language_barrier() -> None:
    # Every severity is exactly 0.30: the read must point at the first
    # barrier in BARRIER_ORDER (language) instead of an arbitrary one.
    out = _build(
        specs={
            "a": _cultural_metrics(
                language=0.70, alignment=0.70, family=0.30,
                religious=0.30, seasonal=0.70, geo=0.70,
            )
        },
        weights={"a": 1.0},
    )
    assert out.cluster_profiles[0].primary_barrier == BARRIER_LANGUAGE
    assert out.cluster_profiles[0].primary_barrier_score == 0.3


def test_tier_boundaries_are_stable() -> None:
    assert _fit_tier(0.75) == TIER_STRONG
    assert _fit_tier(0.55) == TIER_MODERATE
    assert _fit_tier(0.40) == TIER_WEAK
    assert _fit_tier(0.39) == TIER_MISALIGNED


def test_fit_index_is_weighted_composite() -> None:
    assert _fit_index(
        {
            BARRIER_LANGUAGE: 1.0,
            BARRIER_ALIGNMENT: 1.0,
            BARRIER_FAMILY: 1.0,
            BARRIER_RELIGIOUS: 1.0,
            BARRIER_SEASONAL: 1.0,
            BARRIER_GEO: 1.0,
        }
    ) == 0.0
    assert _fit_index(
        {
            BARRIER_LANGUAGE: 0.0,
            BARRIER_ALIGNMENT: 0.0,
            BARRIER_FAMILY: 0.0,
            BARRIER_RELIGIOUS: 0.0,
            BARRIER_SEASONAL: 0.0,
            BARRIER_GEO: 0.0,
        }
    ) == 1.0


def test_moderate_and_weak_verdicts() -> None:
    moderate = _build(
        specs={"a": _cultural_metrics()},
        weights={"a": 1.0},
    )
    assert moderate.verdict == VERDICT_MODERATE_FIT

    weak = _build(
        specs={
            "a": _cultural_metrics(
                alignment=0.50, language=0.50, family=0.60,
                seasonal=0.50, religious=0.40, geo=0.60,
            )
        },
        weights={"a": 1.0},
    )
    assert weak.verdict == VERDICT_WEAK_FIT
    assert weak.fit_index == 0.505
    assert weak.weak_share == 1.0


def test_product_type_is_echoed_and_supported() -> None:
    out = _build(
        specs={"a": _cultural_metrics()},
        weights={"a": 1.0},
        product_type="health_hardware",
    )
    assert out.product_type == "health_hardware"
    assert out.meta["product_type_supported"] is True


def test_conductor_stack_activates_cultural_context_for_all_product_types() -> None:
    """Every product-type stack must both list and activate the architect;
    a stack membership alone is not enough (activation also requires the
    product type to be in ``product_types`` or the list to be empty)."""
    from app.simulation.architects.cultural_context import CulturalContextArchitect
    from app.simulation.conductor import ARCHITECT_STACKS
    from app.simulation.product_type import ProductType

    architect = CulturalContextArchitect()
    for product_type in ProductType:
        assert (
            "CulturalContextArchitect" in ARCHITECT_STACKS[product_type]
        ), product_type.value
        assert (
            not architect.product_types
            or product_type.value in architect.product_types
        ), product_type.value


def test_real_conductor_read_works_for_newer_product_types() -> None:
    """smart_home is one of the product types added after the original ten;
    the cultural-fit read must return a real verdict for it, not
    INSUFFICIENT_DATA with a falsely positive supported flag."""
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.product_type import ProductType

    conductor = Conductor()
    result = conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999.0,
            "price_sensitivity": 0.5,
            "market_maturity": 0.3,
        },
        assumptions=[],
        product_type=ProductType.SMART_HOME,
    )
    assert all(
        "CulturalContextArchitect" in outputs
        for outputs in result.cluster_results.values()
    )

    conductor_results = {
        cid: {
            name: {"metrics": output.metrics, "flags": output.flags}
            for name, output in arch_outputs.items()
        }
        for cid, arch_outputs in result.cluster_results.items()
    }
    registry = [
        {
            "cluster_id": cluster.cluster_id,
            "name": cluster.name,
            "population_weight": cluster.population_weight,
        }
        for cluster in ClusterRegistry().all_clusters()
    ]
    out = build_cultural_fit(
        {},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type="smart_home",
    )

    assert out.verdict != VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is True
    assert out.meta["covered_clusters"] == out.meta["total_clusters"]


def test_meta_supported_flag_reflects_missing_architect_metrics() -> None:
    """When no cluster exposes CulturalContextArchitect metrics, the read is
    INSUFFICIENT_DATA and must not advertise the product type as supported."""
    registry = _registry(
        [{"cluster_id": "a", "name": "A", "population_weight": 1.0}]
    )
    out = build_cultural_fit(
        {},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        conductor_results={
            "a": {"OtherArchitect": {"metrics": {"something": 0.5}, "flags": {}}}
        },
        cluster_registry=registry,
        product_type="smart_home",
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.meta["covered_clusters"] == 0


def test_meta_surface() -> None:
    out = _build(
        specs={"a": _cultural_metrics()},
        weights={"a": 1.0},
    )
    assert out.meta["signal_quality"] == 0.62
    assert out.meta["thresholds"]["tier_strong_index"] == 0.75
    assert out.meta["thresholds"]["verdict_weak_index"] == 0.40
    assert "primary_barrier_score" in out.meta


def test_assumptions_shape_cultural_fit_read_end_to_end() -> None:
    """Regional-language phrasing in the brief must raise the weighted
    language-accessibility score and therefore the overall fit index."""
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.product_type import ProductType

    conductor = Conductor()

    def read_with(assumptions: list[dict]) -> CulturalFitOut:
        result = conductor.run(
            agents=[],
            env_params={
                "average_order_value": 999.0,
                "price_sensitivity": 0.5,
                "market_maturity": 0.3,
            },
            assumptions=assumptions,
            product_type=ProductType.SAAS,
        )
        conductor_results = {
            cid: {
                name: {"metrics": output.metrics, "flags": output.flags}
                for name, output in arch_outputs.items()
            }
            for cid, arch_outputs in result.cluster_results.items()
        }
        registry = [
            {
                "cluster_id": cluster.cluster_id,
                "name": cluster.name,
                "population_weight": cluster.population_weight,
            }
            for cluster in ClusterRegistry().all_clusters()
        ]
        return build_cultural_fit(
            {},
            simulation_id=7,
            project_id=10,
            status="COMPLETED",
            signal_quality=0.62,
            conductor_results=conductor_results,
            cluster_registry=registry,
            product_type="saas",
        )

    without = read_with([])
    with_lang = read_with(
        [
            {
                "text": "The app ships in Hindi and regional languages",
                "sensitivity": "MEDIUM",
                "impact_score": 5.0,
            }
        ]
    )

    assert without.verdict != VERDICT_INSUFFICIENT
    assert with_lang.weighted_language_accessibility > (
        without.weighted_language_accessibility
    )
    assert with_lang.fit_index > without.fit_index

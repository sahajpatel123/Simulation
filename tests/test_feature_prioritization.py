"""
Tests for the pure feature-prioritization builder
(``app.simulation.feature_prioritization``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.feature_prioritization import (
    TIER_BUILD_FIRST,
    TIER_GROW,
    TIER_UNMAPPED,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_FOCUSED,
    VERDICT_INSUFFICIENT,
    VERDICT_READY,
    FeaturePrioritizationOut,
)
from app.simulation.feature_prioritization import (
    DIMENSIONS,
    build_feature_prioritization,
)


def _registry(
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _feature_metrics(
    *,
    depth: float = 0.5,
    dau: float = 0.5,
    discovery: float = 0.35,
    collab: float = 0.2,
    integration: float = 0.3,
    advanced: float = 0.2,
    api: float = 0.1,
    abandonment: float = 0.15,
    export: float = 0.2,
    dashboard: float = 0.2,
) -> dict[str, float]:
    return {
        "core_feature_dau_rate": dau,
        "power_feature_discovery_rate": discovery,
        "feature_depth_score": depth,
        "collaboration_adoption_rate": collab,
        "integration_adoption_rate": integration,
        "advanced_settings_exploration": advanced,
        "api_adoption_rate": api,
        "feature_abandonment_rate": abandonment,
        "export_reporting_usage": export,
        "dashboard_customisation_rate": dashboard,
    }


def _conductor(
    specs: dict[str, dict[str, float]],
) -> dict[str, Any]:
    return {
        cid: {
            "FeatureAdoptionArchitect": {
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
    brief_features: list[str] | None = None,
) -> FeaturePrioritizationOut:
    specs = specs or {
        "a": _feature_metrics(),
        "b": _feature_metrics(depth=0.7, dau=0.7, discovery=0.5, collab=0.4),
        "c": _feature_metrics(depth=0.3, dau=0.3, discovery=0.15),
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
    return build_feature_prioritization(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
        brief_features=brief_features,
    )


def test_happy_path_returns_ranked_dimensions() -> None:
    out = _build()

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert len(out.dimensions) == len(DIMENSIONS)
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["covered_clusters"] == 3
    assert out.meta["product_type_supported"] is True

    scores = [d.priority_score for d in out.dimensions]
    assert scores == sorted(scores, reverse=True)
    assert all(d.priority_tier in VALID_TIERS for d in out.dimensions)
    assert out.dimensions[0].priority_tier == TIER_BUILD_FIRST
    assert len(out.cluster_profiles) == 3
    assert out.recommendations


def test_high_adoption_low_upside_dimension_does_not_lead() -> None:
    # A saturated dimension (99% adoption) must not outrank one with strong
    # adoption and real headroom.
    out = _build(
        specs={
            "saturated": _feature_metrics(
                depth=0.99, dau=0.99, discovery=0.99, collab=0.99,
                integration=0.99, advanced=0.99, api=0.99, export=0.99,
                dashboard=0.99,
            ),
            "growing": _feature_metrics(
                depth=0.55, dau=0.55, discovery=0.4, collab=0.25,
                integration=0.3, advanced=0.25, api=0.15, export=0.2,
                dashboard=0.2,
            ),
        },
        weights={"saturated": 0.5, "growing": 0.5},
    )

    assert out.dimensions[0].key != "core_feature_dau_rate"


def test_shallow_adoption_flag_and_focused_verdict() -> None:
    out = _build(
        specs={
            "shallow": _feature_metrics(depth=0.15),
            "deep": _feature_metrics(depth=0.7),
        },
        weights={"shallow": 0.3, "deep": 0.7},
    )

    assert "shallow_adoption_risk" in out.flags
    assert out.verdict == VERDICT_FOCUSED
    assert any("shallow feature depth" in r for r in out.recommendations)


def test_high_abandonment_flag_uses_raw_abandonment_rate() -> None:
    out = _build(
        specs={
            "churny": _feature_metrics(abandonment=0.6),
            "sticky": _feature_metrics(abandonment=0.1),
        },
        weights={"churny": 0.5, "sticky": 0.5},
    )

    assert "high_abandonment" in out.flags
    assert out.verdict == VERDICT_FOCUSED
    assert any("time-to-value" in r for r in out.recommendations)


def test_low_abandonment_does_not_flag() -> None:
    out = _build(
        specs={
            "a": _feature_metrics(abandonment=0.1),
            "b": _feature_metrics(abandonment=0.15),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert "high_abandonment" not in out.flags


def test_collaboration_blocked_flag() -> None:
    out = _build(
        specs={
            "low_trust": _feature_metrics(collab=0.05),
            "trusting": _feature_metrics(collab=0.08),
        },
        weights={"low_trust": 0.5, "trusting": 0.5},
    )

    assert "collaboration_blocked" in out.flags
    assert out.verdict == VERDICT_FOCUSED


def test_no_api_interest_flag() -> None:
    out = _build(
        specs={
            "a": _feature_metrics(api=0.01),
            "b": _feature_metrics(api=0.02),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert "no_api_interest" in out.flags


def test_power_discovery_gap_flag() -> None:
    out = _build(
        specs={
            "a": _feature_metrics(depth=0.7, discovery=0.2),
            "b": _feature_metrics(depth=0.6, discovery=0.3),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert "power_discovery_gap" in out.flags


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(product_type="wearable")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert out.dimensions == []
    assert out.recommendations


def test_missing_architect_metrics_returns_insufficient_data() -> None:
    out = _build(conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.recommendations


def test_brief_features_map_to_dimensions() -> None:
    out = _build(
        brief_features=[
            "Slack integration",
            "One-click export",
            "Team workspaces",
            "Advanced analytics dashboard",
            "Rapid onboarding",
        ]
    )

    by_feature = {b.feature: b for b in out.brief_features}
    assert by_feature["Slack integration"].dimension_key == "integration_adoption_rate"
    assert by_feature["Slack integration"].priority_tier in {
        TIER_BUILD_FIRST,
        TIER_GROW,
    }
    # "click" must not match the "cli" keyword.
    assert by_feature["One-click export"].dimension_key == "export_reporting_usage"
    # "analytics" maps to the dashboard dimension, not export.
    assert (
        by_feature["Advanced analytics dashboard"].dimension_key
        == "dashboard_customisation_rate"
    )
    assert by_feature["Team workspaces"].dimension_key == "collaboration_adoption_rate"
    assert by_feature["Rapid onboarding"].dimension_key is None
    assert by_feature["Rapid onboarding"].priority_tier == TIER_UNMAPPED


def test_brief_features_coerce_from_json_string() -> None:
    out = _build(brief_features='["Slack integration", "  ", "Export CSV"]')

    assert [b.feature for b in out.brief_features] == [
        "Slack integration",
        "Export CSV",
    ]
    assert out.brief_features[1].dimension_key == "export_reporting_usage"


def test_brief_features_non_list_coerces_to_empty() -> None:
    out = _build(brief_features={"not": "a list"})

    assert out.brief_features == []


def test_cluster_segment_tiers() -> None:
    out = _build(
        specs={
            "advanced": _feature_metrics(depth=0.7),
            "mainstream": _feature_metrics(depth=0.4),
            "lagging": _feature_metrics(depth=0.2),
        },
        weights={"advanced": 0.4, "mainstream": 0.4, "lagging": 0.2},
    )

    tiers = {c.cluster_id: c.segment_tier for c in out.cluster_profiles}
    assert tiers["advanced"] == "ADVANCED"
    assert tiers["mainstream"] == "MAINSTREAM"
    assert tiers["lagging"] == "LAGGING"
    # ADVANCED segments sort first.
    assert out.cluster_profiles[0].cluster_id == "advanced"


def test_healthy_run_is_ready() -> None:
    out = _build(
        specs={
            "a": _feature_metrics(
                depth=0.6, dau=0.6, discovery=0.5, collab=0.25,
                integration=0.4, advanced=0.3, api=0.12, export=0.25,
                dashboard=0.25,
            ),
            "b": _feature_metrics(
                depth=0.65, dau=0.65, discovery=0.55, collab=0.3,
                integration=0.45, advanced=0.35, api=0.15, export=0.3,
                dashboard=0.3,
            ),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict == VERDICT_READY
    assert out.flags == []


def test_recommendation_lists_top_dimension() -> None:
    out = _build()

    top = out.dimensions[0]
    assert any(top.label in r for r in out.recommendations)

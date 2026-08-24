"""
Tests for the pure retention-churn builder
(``app.simulation.retention_churn_read``).
"""
from __future__ import annotations

from typing import Any

import pytest

from app.schemas.retention_churn import (
    LEVER_ONBOARDING,
    TIER_FADING,
    TIER_HIGH_CHURN,
    TIER_STEADY,
    TIER_STICKY,
    TRIGGER_FEATURE,
    TRIGGER_HABIT,
    TRIGGER_ONBOARDING,
    TRIGGER_PRICE,
    VALID_VERDICTS,
    VERDICT_CRITICAL,
    VERDICT_INSUFFICIENT,
    VERDICT_MODERATE,
    VERDICT_STRONG,
    VERDICT_WEAK,
    RetentionChurnOut,
)
from app.simulation.architects.retention import RetentionArchitect
from app.simulation.conductor import ARCHITECT_STACKS
from app.simulation.retention_churn_read import (
    RETENTION_PRODUCT_TYPES,
    build_retention_churn,
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


def _retention_metrics(
    *,
    day1: float = 0.70,
    day7: float = 0.45,
    day30: float = 0.28,
    day90: float = 0.18,
    habit_days: float = 18.0,
    reeng_30: float = 0.12,
    notif: float = 0.20,
    pause: float = 0.35,
    session_depth: float = 0.3,
) -> dict[str, float]:
    return {
        "day1_survival": day1,
        "day7_survival": day7,
        "day30_survival": day30,
        "day90_survival": day90,
        "habit_loop_formation_days": habit_days,
        "reengagement_probability_30d": reeng_30,
        "reengagement_probability_90d": round(reeng_30 * 0.45, 4),
        "notification_reengagement_rate": notif,
        "pause_vs_cancel_preference": pause,
        "session_depth_score": session_depth,
    }


def _pricing_metrics(*, will_pay: float = 0.55) -> dict[str, float]:
    return {"will_pay_probability": will_pay}


def _onboarding_metrics(*, completion: float = 0.75) -> dict[str, float]:
    return {"onboarding_completion_rate": completion}


def _feature_metrics(*, depth: float = 0.60) -> dict[str, float]:
    return {"feature_depth_score": depth}


def _support_metrics(*, tickets: float = 0.25) -> dict[str, float]:
    return {"support_ticket_likelihood": tickets}


def _pick(
    per_cluster: dict[str, dict[str, float]] | None,
    default: dict[str, float],
    cid: str,
) -> dict[str, float]:
    if per_cluster and cid in per_cluster:
        return per_cluster[cid]
    return default


def _conductor(
    specs: dict[str, dict[str, float]],
    *,
    pricing: dict[str, float] | None = None,
    onboarding: dict[str, float] | None = None,
    feature: dict[str, float] | None = None,
    support: dict[str, float] | None = None,
) -> dict[str, Any]:
    return {
        cid: {
            "RetentionArchitect": {"metrics": metrics, "flags": {}},
            "PricingArchitect": {
                "metrics": _pick(pricing, _pricing_metrics(), cid),
                "flags": {},
            },
            "OnboardingArchitect": {
                "metrics": _pick(onboarding, _onboarding_metrics(), cid),
                "flags": {},
            },
            "FeatureAdoptionArchitect": {
                "metrics": _pick(feature, _feature_metrics(), cid),
                "flags": {},
            },
            "SupportFrictionArchitect": {
                "metrics": _pick(support, _support_metrics(), cid),
                "flags": {},
            },
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
    pricing: dict[str, float] | None = None,
    onboarding: dict[str, float] | None = None,
    feature: dict[str, float] | None = None,
    support: dict[str, float] | None = None,
) -> RetentionChurnOut:
    specs = specs or {
        "a": _retention_metrics(),
        "b": _retention_metrics(day30=0.40, day90=0.30, habit_days=10.0),
        "c": _retention_metrics(day7=0.15, day30=0.05, day90=0.02),
    }
    if weights is None:
        equal_weight = 1.0 / len(specs) if specs else 1.0
        weights = {cid: equal_weight for cid in specs}
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
        conductor_results = _conductor(
            specs,
            pricing=pricing,
            onboarding=onboarding,
            feature=feature,
            support=support,
        )
    return build_retention_churn(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_ranked_retention_payload() -> None:
    out = _build()

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict != VERDICT_INSUFFICIENT
    assert len(out.cluster_profiles) == 3
    assert len(out.levers) == 6
    assert out.recommendations
    assert out.meta["covered_clusters"] == 3
    assert out.meta["covered_weight"] == 1.0
    assert all(
        0.0 <= share <= 1.0
        for share in (
            out.sticky_share,
            out.steady_share,
            out.fading_share,
            out.high_churn_share,
        )
    )
    assert sum(
        (
            out.sticky_share,
            out.steady_share,
            out.fading_share,
            out.high_churn_share,
        )
    ) == pytest.approx(1.0, abs=0.01)
    assert all(lever.opportunity_share >= 0.0 for lever in out.levers)


def test_tiers_follow_survival_thresholds() -> None:
    out = _build(
        specs={
            "sticky": _retention_metrics(day30=0.40, day90=0.30),
            "steady": _retention_metrics(day30=0.30, day90=0.12),
            "fading": _retention_metrics(day30=0.15, day90=0.05),
            "churn": _retention_metrics(day30=0.04, day90=0.01),
        }
    )
    tiers = {p.cluster_id: p.retention_tier for p in out.cluster_profiles}
    assert tiers == {
        "sticky": TIER_STICKY,
        "steady": TIER_STEADY,
        "fading": TIER_FADING,
        "churn": TIER_HIGH_CHURN,
    }


def test_verdicts_follow_weighted_survival() -> None:
    strong = _build(
        specs={
            "a": _retention_metrics(day30=0.45, day90=0.30),
            "b": _retention_metrics(day30=0.40, day90=0.28),
        }
    )
    assert strong.verdict == VERDICT_STRONG

    moderate = _build(
        specs={
            "a": _retention_metrics(day30=0.30, day90=0.12),
            "b": _retention_metrics(day30=0.28, day90=0.10),
        }
    )
    assert moderate.verdict == VERDICT_MODERATE

    weak = _build(
        specs={
            "a": _retention_metrics(day30=0.14, day90=0.05),
            "b": _retention_metrics(day30=0.12, day90=0.04),
        }
    )
    assert weak.verdict == VERDICT_WEAK

    critical = _build(
        specs={
            "a": _retention_metrics(day30=0.06, day90=0.02),
            "b": _retention_metrics(day30=0.05, day90=0.01),
        }
    )
    assert critical.verdict == VERDICT_CRITICAL


def test_primary_trigger_uses_weighted_distribution() -> None:
    out = _build(
        specs={
            "price": _retention_metrics(),
            "onboard": _retention_metrics(),
            "feature": _retention_metrics(day7=0.45, day30=0.05),
        },
        pricing={"price": _pricing_metrics(will_pay=0.20)},
        onboarding={"onboard": _onboarding_metrics(completion=0.35)},
    )

    assert out.primary_churn_trigger in {
        TRIGGER_PRICE,
        TRIGGER_ONBOARDING,
        TRIGGER_FEATURE,
    }
    assert out.churn_trigger_distribution
    assert sum(out.churn_trigger_distribution.values()) == pytest.approx(
        1.0, abs=0.01
    )
    # The weak will-pay cluster gets price attribution; the weak onboarding
    # cluster gets onboarding; the day7→day30 cliff gets feature.
    assert out.churn_trigger_distribution[TRIGGER_PRICE] > 0.0
    assert out.churn_trigger_distribution[TRIGGER_ONBOARDING] > 0.0
    assert out.churn_trigger_distribution[TRIGGER_FEATURE] > 0.0


def test_habit_trigger_attributed_when_habit_loop_is_slow() -> None:
    out = _build(
        specs={
            "a": _retention_metrics(habit_days=55.0),
            "b": _retention_metrics(habit_days=58.0),
        }
    )
    profiles = {p.cluster_id: p.primary_churn_trigger for p in out.cluster_profiles}
    assert profiles == {"a": TRIGGER_HABIT, "b": TRIGGER_HABIT}
    assert out.primary_churn_trigger == TRIGGER_HABIT


def test_highest_churn_stage_identified() -> None:
    # Big day-30 drop: 0.75 → 0.55 → 0.18 → 0.10.
    out = _build(
        specs={
            "a": _retention_metrics(day1=0.75, day7=0.55, day30=0.18, day90=0.10),
            "b": _retention_metrics(day1=0.75, day7=0.55, day30=0.18, day90=0.10),
        }
    )
    assert out.highest_churn_stage == "day30"
    assert "churn_cliff_day30" in out.flags


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(product_type="iot_hardware")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert "iot_hardware" in out.recommendations[0]


def test_no_metrics_returns_insufficient_data() -> None:
    out = _build(
        specs={
            "a": _retention_metrics(),
            "b": _retention_metrics(),
        },
        conductor_results={
            "a": {"RetentionArchitect": {"metrics": {}, "flags": {}}},
            "b": {},
        },
    )

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0


def test_missing_fields_use_conservative_defaults() -> None:
    out = _build(
        specs={
            "a": _retention_metrics(),
        },
        conductor_results={
            "a": {
                "RetentionArchitect": {
                    "metrics": {"day1_survival": 0.5},
                    "flags": {},
                }
            },
        },
        registry=_registry(
            [{"cluster_id": "a", "name": "A", "population_weight": 1.0}]
        ),
    )

    # Missing survival metrics must never manufacture a healthy read.
    assert out.weighted_day90_survival == 0.04
    assert out.weighted_habit_loop_days == 60.0
    assert out.verdict == VERDICT_CRITICAL
    assert "critical_retention_risk" in out.flags
    assert "habit_loop_unlikely" in out.flags


def test_levers_ranked_by_opportunity_share() -> None:
    out = _build(
        specs={
            "a": _retention_metrics(day30=0.30, day90=0.15),
            "b": _retention_metrics(day30=0.30, day90=0.15),
        },
        onboarding={"a": _onboarding_metrics(completion=0.5)},
    )

    assert out.levers == sorted(
        out.levers, key=lambda lever: (-lever.opportunity_share, lever.key)
    )
    onboarding_lever = next(
        lever for lever in out.levers if lever.key == LEVER_ONBOARDING
    )
    assert onboarding_lever.opportunity_share > 0.0
    assert onboarding_lever.market_value < 0.70


def test_deep_work_share_tracks_session_patterns() -> None:
    out = _build(
        specs={
            "a": _retention_metrics(session_depth=1.0),
            "b": _retention_metrics(session_depth=1.0),
        }
    )
    assert out.deep_work_share == 1.0
    assert "deep_work_dominant" in out.flags


def test_supported_product_types_cover_retention_stacks() -> None:
    assert "saas" in RETENTION_PRODUCT_TYPES
    assert "d2c" in RETENTION_PRODUCT_TYPES
    assert "iot_hardware" not in RETENTION_PRODUCT_TYPES


def test_supported_set_matches_conductor_activation() -> None:
    """Every advertised product type must actually run RetentionArchitect."""
    activated = {
        pt.value
        for pt, stack in ARCHITECT_STACKS.items()
        if "RetentionArchitect" in stack
        and pt.value in RetentionArchitect().product_types
    }
    assert RETENTION_PRODUCT_TYPES == activated

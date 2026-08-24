"""
Tests for the pure activation-funnel builder
(``app.simulation.activation_funnel``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.activation_funnel import (
    BLOCKER_COMPLETION,
    BLOCKER_EMPTY_STATE,
    TIER_CRITICAL,
    TIER_MODERATE,
    TIER_STRONG,
    TIER_WEAK,
    VALID_TIERS,
    VALID_VERDICTS,
    VERDICT_AT_RISK,
    VERDICT_BLOCKED,
    VERDICT_INSUFFICIENT,
    VERDICT_READY,
    ActivationFunnelOut,
)
from app.simulation.activation_funnel import (
    ACTIVATION_PRODUCT_TYPES,
    BLOCKER_ORDER,
    build_activation_funnel,
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


def _onboarding_metrics(
    *,
    completion: float = 0.72,
    ttfv: float = 7.0,
    empty_bounce: float = 0.25,
    disclosure: float = 8.0,
    mobile: float = 0.0,
    permission: float = 0.15,
    mandatory: float = 0.12,
    video_skip: float = 0.30,
    social_lift: float = 0.12,
    template_pref: float = 0.40,
    id_friction: float = 0.10,
) -> dict[str, float]:
    return {
        "onboarding_completion_rate": completion,
        "time_to_first_value_tolerance": ttfv,
        "empty_state_bounce_probability": empty_bounce,
        "progressive_disclosure_limit": disclosure,
        "mobile_completion_penalty": mobile,
        "permission_timing_sensitivity": permission,
        "mandatory_profile_churn_risk": mandatory,
        "video_walkthrough_skip_rate": video_skip,
        "social_onboarding_lift": social_lift,
        "template_vs_blank_preference": template_pref,
        "identity_verification_friction": id_friction,
    }


def _conductor(
    specs: dict[str, dict[str, float]],
) -> dict[str, Any]:
    return {
        cid: {
            "OnboardingArchitect": {
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
) -> ActivationFunnelOut:
    specs = specs or {
        "a": _onboarding_metrics(),
        "b": _onboarding_metrics(completion=0.85, ttfv=10.0, empty_bounce=0.10),
        "c": _onboarding_metrics(completion=0.55, ttfv=4.0, empty_bounce=0.35),
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
    return build_activation_funnel(
        {"product_type_detected": product_type},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        product_type=product_type,
    )


def test_happy_path_returns_ranked_activation_payload() -> None:
    out = _build()

    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.verdict in VALID_VERDICTS
    assert out.verdict != VERDICT_INSUFFICIENT
    assert 0.0 <= out.activation_rate <= 1.0
    assert len(out.cluster_profiles) == 3
    assert all(p.activation_tier in VALID_TIERS for p in out.cluster_profiles)
    assert out.meta["covered_weight"] == 1.0
    assert out.meta["product_type_supported"] is True
    assert len(out.levers) == 7
    assert [lever.opportunity_share for lever in out.levers] == sorted(
        [lever.opportunity_share for lever in out.levers], reverse=True
    )
    assert out.recommendations
    assert sum(out.blocker_distribution.values()) > 0.99


def test_healthy_completion_verdict_ready() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.90, ttfv=12.0),
            "b": _onboarding_metrics(completion=0.88, ttfv=11.0),
            "c": _onboarding_metrics(completion=0.85, ttfv=10.0),
        },
        weights={"a": 0.4, "b": 0.3, "c": 0.3},
    )

    assert out.verdict == VERDICT_READY
    assert out.activation_rate >= 0.85
    assert not out.flags


def test_critical_completion_verdict_blocked() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.30),
            "b": _onboarding_metrics(completion=0.80),
        },
        weights={"a": 0.8, "b": 0.2},
    )

    assert out.verdict == VERDICT_BLOCKED
    assert "completion_critical" in out.flags
    assert "critical_activation_share" in out.flags
    assert out.cluster_profiles[0].activation_tier == TIER_CRITICAL
    assert out.cluster_profiles[0].primary_blocker == BLOCKER_COMPLETION
    assert any("blocked" in r for r in out.recommendations)


def test_moderate_completion_verdict_at_risk() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.55),
            "b": _onboarding_metrics(completion=0.85),
            "c": _onboarding_metrics(completion=0.80),
        },
        weights={"a": 0.4, "b": 0.3, "c": 0.3},
    )

    assert out.verdict == VERDICT_AT_RISK
    assert any("at risk" in r for r in out.recommendations)


def test_weak_tier_share_can_drive_at_risk_with_decent_completion() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.75, empty_bounce=0.70),
            "b": _onboarding_metrics(completion=0.75, empty_bounce=0.70),
            "c": _onboarding_metrics(completion=0.90, empty_bounce=0.05),
        },
        weights={"a": 0.3, "b": 0.3, "c": 0.4},
    )

    assert out.verdict == VERDICT_AT_RISK
    assert "empty_state_risk" in out.flags
    assert out.cluster_profiles[0].activation_tier == TIER_WEAK


def test_mobile_gap_share_drives_at_risk() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.85, mobile=0.35),
            "b": _onboarding_metrics(completion=0.85, mobile=0.35),
            "c": _onboarding_metrics(completion=0.90),
        },
        weights={"a": 0.3, "b": 0.3, "c": 0.4},
    )

    assert out.verdict == VERDICT_AT_RISK
    assert "mobile_gap" in out.flags
    assert out.mobile_gap_share > 0.15
    assert any("Mobile" in r for r in out.recommendations)


def test_unsupported_product_type_returns_insufficient_data() -> None:
    out = _build(product_type="consumer_hardware")

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["product_type_supported"] is False
    assert "consumer_hardware" in out.recommendations[0]
    assert "consumer_hardware" not in ACTIVATION_PRODUCT_TYPES


def test_missing_conductor_metrics_returns_insufficient_data() -> None:
    out = _build(conductor_results={})

    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.meta["covered_clusters"] == 0
    assert out.meta["covered_weight"] == 0.0


def test_malformed_metric_values_do_not_crash() -> None:
    bad_metrics = _onboarding_metrics()
    bad_metrics["onboarding_completion_rate"] = "not-a-number"
    bad_metrics["empty_state_bounce_probability"] = None
    bad_metrics["time_to_first_value_tolerance"] = True
    bad_metrics["identity_verification_friction"] = float("nan")
    out = _build(
        specs={
            "a": bad_metrics,
            "b": _onboarding_metrics(),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert out.verdict in VALID_VERDICTS
    assert 0.0 <= out.activation_rate <= 1.0
    assert out.cluster_profiles[0].primary_blocker in BLOCKER_ORDER


def test_missing_time_to_value_uses_neutral_default_consistently() -> None:
    metrics = _onboarding_metrics()
    del metrics["time_to_first_value_tolerance"]
    out = _build(specs={"a": metrics}, weights={"a": 1.0})

    assert out.cluster_profiles[0].time_to_first_value_tolerance == 6.0
    assert out.time_to_first_value_minutes == 6.0
    assert "time_to_value_impatience" not in out.flags
    assert not any("tolerance is only" in r for r in out.recommendations)


def test_explicit_short_time_to_value_still_flags_impatience() -> None:
    out = _build(
        specs={"a": _onboarding_metrics(ttfv=2.0)},
        weights={"a": 1.0},
    )

    assert out.cluster_profiles[0].time_to_first_value_tolerance == 2.0
    assert "time_to_value_impatience" in out.flags


def test_missing_disclosure_limit_does_not_fabricate_lever_opportunity() -> None:
    metrics = _onboarding_metrics()
    del metrics["progressive_disclosure_limit"]
    out = _build(specs={"a": metrics}, weights={"a": 1.0})

    assert out.cluster_profiles[0].progressive_disclosure_limit == 18.0
    disclosure_lever = next(
        lever for lever in out.levers if lever.key == "progressive_disclosure"
    )
    assert disclosure_lever.opportunity_share == 0.0


def test_levers_ranked_and_opportunity_shares_are_population_weighted() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.30),
            "b": _onboarding_metrics(completion=0.90),
            "c": _onboarding_metrics(completion=0.80),
        },
        weights={"a": 0.4, "b": 0.3, "c": 0.3},
    )

    assert out.levers[0].key == "simplify_onboarding"
    assert out.levers[0].opportunity_share == 0.4
    assert any(
        lever.key == "templates_first_run" and lever.opportunity_share >= 0.0
        for lever in out.levers
    )


def test_primary_blocker_prefers_completion_on_tie() -> None:
    from app.simulation.activation_funnel import _primary_blocker

    scores = {
        BLOCKER_COMPLETION: 0.5,
        BLOCKER_EMPTY_STATE: 0.5,
        "identity_friction": 0.5,
        "mandatory_profile": 0.5,
        "mobile_gap": 0.5,
        "permission_timing": 0.5,
        "time_to_value": 0.5,
    }
    blocker, score = _primary_blocker(scores)
    assert blocker == BLOCKER_COMPLETION
    assert score == 0.5


def test_primary_blocker_picks_highest_score() -> None:
    from app.simulation.activation_funnel import _primary_blocker

    scores = {
        BLOCKER_COMPLETION: 0.1,
        BLOCKER_EMPTY_STATE: 0.7,
        "identity_friction": 0.2,
        "mandatory_profile": 0.2,
        "mobile_gap": 0.1,
        "permission_timing": 0.2,
        "time_to_value": 0.1,
    }
    blocker, _ = _primary_blocker(scores)
    assert blocker == BLOCKER_EMPTY_STATE


def test_activation_tier_classification() -> None:
    from app.simulation.activation_funnel import _activation_tier

    assert _activation_tier(0.30, 0.1, 0.0) == TIER_CRITICAL
    assert _activation_tier(0.50, 0.1, 0.0) == TIER_WEAK
    assert _activation_tier(0.72, 0.1, 0.0) == TIER_MODERATE
    assert _activation_tier(0.90, 0.1, 0.0) == TIER_STRONG
    assert _activation_tier(0.75, 0.60, 0.0) == TIER_WEAK
    assert _activation_tier(0.75, 0.1, 0.25) == TIER_WEAK


def test_identity_friction_flag_and_recommendation() -> None:
    out = _build(
        specs={
            "a": _onboarding_metrics(completion=0.80, id_friction=0.6),
            "b": _onboarding_metrics(completion=0.85),
        },
        weights={"a": 0.5, "b": 0.5},
    )

    assert "identity_friction" in out.flags
    assert any("verification" in r for r in out.recommendations)
    assert out.identity_friction_weighted > 0.20

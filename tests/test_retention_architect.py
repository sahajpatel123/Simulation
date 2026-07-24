"""
Tests for ``app.simulation.architects.retention`` — RetentionArchitect.

Locks down survival-curve math, use-frequency multipliers, habit
formation rules, churn trigger, notification / streak / pause
metrics, severity tiers, flags, narrative findings,
transition_overrides, and generate_report() cross-cluster rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    motivation: float = 0.5,
    patience: float = 0.5,
    trust: float = 0.5,
    price_sens: float = 0.5,
    income: float = 0.5,
    literacy: float = 0.5,
    risk: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    age_bracket: str = "25-35",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.1,
        base_traits={
            "income_level": income,
            "digital_literacy": literacy,
            "motivation": motivation,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": patience,
            "social_orientation": social,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={"geography": "metro_delhi", "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_retention_architect_name_constant() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    assert RetentionArchitect().name == "RetentionArchitect"


def test_retention_architect_product_types_subset() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    pt = RetentionArchitect().product_types
    # Same software subset as OnboardingArchitect (no hardware).
    for p in pt:
        assert "hardware" not in p.lower()


# ---------------------------------------------------------------------------
# Metric surface + survival caps
# ---------------------------------------------------------------------------


def test_compute_returns_twelve_metrics() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={}
    )
    assert out.architect_name == "RetentionArchitect"
    assert len(out.metrics) == 12


def test_survival_curve_per_stage_caps() -> None:
    """Per-stage caps: day1 0.95, day7 0.90, day30 0.85, day90 0.80."""
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 1.0,
            "onboarding_completion_rate": 1.0,
        },
        assumptions=[], env_params={},
    )
    assert out.metrics["day1_survival"] <= 0.95
    assert out.metrics["day7_survival"] <= 0.90
    assert out.metrics["day30_survival"] <= 0.85
    assert out.metrics["day90_survival"] <= 0.80


def test_survival_curve_non_negative() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.0,
            "onboarding_completion_rate": 0.0,
        },
        assumptions=[], env_params={},
    )
    for key in ("day1_survival", "day7_survival", "day30_survival", "day90_survival"):
        assert out.metrics[key] >= 0.0


# ---------------------------------------------------------------------------
# Survival dependencies
# ---------------------------------------------------------------------------


def test_higher_feature_depth_yields_higher_day1() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    base = {"onboarding_completion_rate": 0.85}
    low = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={**base, "feature_depth_score": 0.1},
        assumptions=[], env_params={},
    )
    high = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={**base, "feature_depth_score": 0.9},
        assumptions=[], env_params={},
    )
    # > 0.4 threshold changes the multiplier from 0.85 to 1.15.
    assert high.metrics["day1_survival"] > low.metrics["day1_survival"]


def test_higher_onboarding_completion_yields_higher_day1() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    low = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.5,
            "onboarding_completion_rate": 0.2,
        },
        assumptions=[], env_params={},
    )
    high = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.5,
            "onboarding_completion_rate": 0.85,
        },
        assumptions=[], env_params={},
    )
    assert high.metrics["day1_survival"] > low.metrics["day1_survival"]


# ---------------------------------------------------------------------------
# Use frequency
# ---------------------------------------------------------------------------


def test_use_frequency_default_daily() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Users log in to manage tasks."}],
        env_params={},
    )
    # 1.2 freq mult → day7 higher than weekly.
    assert "daily" in " ".join(out.narrative_findings).lower()


def test_use_frequency_weekly_from_assumption() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Users typically log in weekly."}],
        env_params={},
    )
    assert "weekly" in " ".join(out.narrative_findings).lower()


def test_use_frequency_monthly_or_as_needed() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Users log in monthly."}],
        env_params={},
    )
    assert "as_needed" in " ".join(out.narrative_findings).lower()


# ---------------------------------------------------------------------------
# Habit formation + churn
# ---------------------------------------------------------------------------


def test_habit_loop_formation_at_least_seven_days() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=1.0),  # max motivation → habit_base < 7
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["habit_loop_formation_days"] >= 7


def test_habit_loop_shortened_for_daily_use() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    weekly = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.5), agent_profile={},
        assumptions=[{"text": "Users log in weekly."}],
        env_params={},
    )
    daily = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.5), agent_profile={},
        assumptions=[], env_params={},
    )
    assert daily.metrics["habit_loop_formation_days"] < weekly.metrics["habit_loop_formation_days"]


def test_habit_unlikely_flag_when_over_45_days() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.05), agent_profile={},
        # as_needed use frequency → 1.8 multiplier on habit_days
        assumptions=[{"text": "Users log in as needed."}],
        env_params={},
    )
    assert out.flags["habit_unlikely"] is True


def test_churn_trigger_threshold_floor_at_one() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(patience=0.0, trust=0.4),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["churn_trigger_threshold"] >= 1


def test_churn_trigger_higher_for_high_patience() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    low = RetentionArchitect().compute(
        cluster=_cluster(patience=0.1), agent_profile={},
        assumptions=[], env_params={},
    )
    high = RetentionArchitect().compute(
        cluster=_cluster(patience=0.9), agent_profile={},
        assumptions=[], env_params={},
    )
    assert high.metrics["churn_trigger_threshold"] > low.metrics["churn_trigger_threshold"]


# ---------------------------------------------------------------------------
# Re-engagement + caps
# ---------------------------------------------------------------------------


def test_notification_reengagement_capped_at_060() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=1.0, trust=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["notification_reengagement_rate"] <= 0.60


def test_streak_response_capped_at_050() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=1.0, age_bracket="18-24"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["streak_gamification_response"] <= 0.50


def test_streak_higher_for_young_age_bracket() -> None:
    """18-22 ages → streak × 1.5 vs 0.6 default."""
    from app.simulation.architects.retention import RetentionArchitect

    old = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.5, age_bracket="55+"),
        agent_profile={}, assumptions=[], env_params={},
    )
    young = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.5, age_bracket="18-24"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert young.metrics["streak_gamification_response"] > old.metrics["streak_gamification_response"]


def test_pause_vs_cancel_capped_at_080() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(income=1.0),  # doesn't directly raise, but verifies cap
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["pause_vs_cancel_preference"] <= 0.80


def test_pause_pref_higher_for_high_income() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    poor = RetentionArchitect().compute(
        cluster=_cluster(income=0.1), agent_profile={},
        assumptions=[], env_params={},
    )
    rich = RetentionArchitect().compute(
        cluster=_cluster(income=1.0), agent_profile={},
        assumptions=[], env_params={},
    )
    assert rich.metrics["pause_vs_cancel_preference"] > poor.metrics["pause_vs_cancel_preference"]


def test_reeng_30_capped_at_040_and_reeng_90_at_020() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=1.0, trust=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["reengagement_probability_30d"] <= 0.40
    assert out.metrics["reengagement_probability_90d"] <= 0.20


# ---------------------------------------------------------------------------
# Session pattern
# ---------------------------------------------------------------------------


def test_session_pattern_deep_when_motivation_and_patience_high() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.9, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["session_pattern_deep"] is True


def test_session_pattern_quick_when_either_low() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.2, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["session_pattern_deep"] is False


def test_session_depth_score_is_binary() -> None:
    """Either 1.0 (deep) or 0.3 (quick) per the formula."""
    from app.simulation.architects.retention import RetentionArchitect

    for motivation, patience in [(0.9, 0.9), (0.5, 0.5), (0.1, 0.1)]:
        out = RetentionArchitect().compute(
            cluster=_cluster(motivation=motivation, patience=patience),
            agent_profile={}, assumptions=[], env_params={},
        )
        assert out.metrics["session_depth_score"] in {1.0, 0.3}


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_critical_when_day7_below_020() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.1,
            "onboarding_completion_rate": 0.1,
        },
        assumptions=[], env_params={},
    )
    assert out.metrics["day7_survival"] < 0.20
    assert out.severity == "CRITICAL"


def test_severity_warning_when_day7_between_020_and_035() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.4,
            "onboarding_completion_rate": 0.55,
        },
        assumptions=[], env_params={},
    )
    # day7 between 0.20 and 0.35 → WARNING.
    assert 0.20 <= out.metrics["day7_survival"] <= 0.35
    assert out.severity == "WARNING"


def test_severity_info_with_high_day7() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.9,
            "onboarding_completion_rate": 0.9,
        },
        assumptions=[], env_params={},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_flag_retention_critical_matches_day7_below_020() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(),
        agent_profile={
            "feature_depth_score": 0.1,
            "onboarding_completion_rate": 0.1,
        },
        assumptions=[], env_params={},
    )
    assert out.flags["retention_critical"] is True
    assert out.severity == "CRITICAL"


def test_flag_reengagement_possible_when_reeng_30d_above_015() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(motivation=0.9, trust=0.9),  # reeng_30 ≈ 0.225
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["reengagement_possible"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_three_narrative_findings() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    out = RetentionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 3
    joined = " | ".join(out.narrative_findings)
    assert "Day-7" in joined
    assert "habit loop" in joined.lower() or "habit" in joined.lower()
    assert "Session pattern" in joined


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_purchase_to_return_uses_day7() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    a = RetentionArchitect()
    out = a.compute(
        cluster=_cluster(),
        agent_profile={"feature_depth_score": 0.5, "onboarding_completion_rate": 0.7},
        assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    val = overrides[("PURCHASE", "RETURN")]
    assert 0.05 <= val <= 0.90
    assert val == max(0.05, min(0.90, out.metrics["day7_survival"]))


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_no_critical_handles_empty() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    a = RetentionArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_critical_clusters() -> None:
    from app.simulation.architects.retention import RetentionArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = RetentionArchitect()
    crit = ArchitectOutput(
        architect_name="RetentionArchitect",
        cluster_id="tier3_critical",
        metrics={},
        flags={"retention_critical": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    ok = ArchitectOutput(
        architect_name="RetentionArchitect",
        cluster_id="metro_ok",
        metrics={},
        flags={"retention_critical": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([crit, ok])
    assert report.severity == "CRITICAL"
    assert "tier3_critical" in report.affected_cluster_ids
    assert "metro_ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.retention import RetentionArchitect

    a = RetentionArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

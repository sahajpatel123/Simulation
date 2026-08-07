"""
Tests for the founder action plan digest
(pure builder + schema contracts, cycle ADD founder-action-plan).
"""
from __future__ import annotations

from typing import Any

from app.schemas.founder_action_plan import (
    EFFORT_HIGH,
    EFFORT_LOW,
    EFFORT_MEDIUM,
    FounderActionPlanOut,
)
from app.simulation.founder_action_plan import (
    MAX_ACTIONS,
    SOURCE_DOMAIN_FINDING,
    SOURCE_FUNNEL,
    build_founder_action_plan,
)


def _results(
    *,
    cr: float = 0.031,
    include_findings: bool = True,
    include_stages: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": 10000,
        "primary_failure_domain": "PricingArchitect",
        "product_type_detected": "saas",
        "cluster_breakdown": {"cluster_a": 0.05, "cluster_b": 0.02},
    }
    if include_findings:
        payload["domain_findings"] = [
            {
                "architect_name": "PricingArchitect",
                "cluster_id": "cluster_b",
                "cluster_name": "Budget Shoppers",
                "metric_affected": "will_pay_probability",
                "finding": "Only 20% of Budget Shoppers will pay at current price.",
                "recommended_action": "Simplify pricing or add a cheaper tier.",
                "severity": "CRITICAL",
                "actual_value": 0.2,
                "healthy_benchmark": 0.4,
                "conversion_impact": 0.05,
                "affected_agent_count": 1200,
            },
            {
                "architect_name": "OnboardingArchitect",
                "cluster_id": "cluster_a",
                "cluster_name": "Power Pros",
                "metric_affected": "onboarding_completion_rate",
                "finding": "Only 40% of Power Pros complete onboarding.",
                "recommended_action": "Cut onboarding steps.",
                "severity": "WARNING",
                "actual_value": 0.4,
                "healthy_benchmark": 0.65,
                "conversion_impact": 0.02,
                "affected_agent_count": 900,
            },
        ]
    if include_stages:
        payload["stage_metrics"] = [
            {"state": "ARRIVE", "agent_count": 10000, "drop_off_rate": 0.10},
            {"state": "BROWSE", "agent_count": 9000, "drop_off_rate": 0.30},
            {"state": "CONSIDER", "agent_count": 6300, "drop_off_rate": 0.35},
            {"state": "DECIDE", "agent_count": 2000, "drop_off_rate": 0.82},
            {"state": "PURCHASE", "agent_count": 310, "drop_off_rate": 0.0},
            {"state": "ABANDON", "agent_count": 9690, "drop_off_rate": 0.0},
        ]
    return payload


def test_empty_results_yield_empty_plan() -> None:
    out = build_founder_action_plan(None, simulation_id=1, project_id=2)
    assert isinstance(out, FounderActionPlanOut)
    assert out.actions == []
    assert out.summary.total_actions == 0
    assert out.summary.verdict == "INSUFFICIENT_DATA"
    assert out.headline_conversion is None


def test_plan_ranks_domain_findings_and_funnel_bottleneck() -> None:
    out = build_founder_action_plan(
        _results(),
        simulation_id=11,
        project_id=12,
        signal_quality=0.8,
    )

    assert out.simulation_id == 11
    assert out.project_id == 12
    assert out.primary_bottleneck == "DECIDE"
    assert out.headline_conversion == 0.031
    assert out.signal_quality == 0.8

    # First action is the highest-impact domain finding; the funnel
    # bottleneck is always represented as an action.
    assert out.actions[0].source == SOURCE_DOMAIN_FINDING
    assert out.actions[0].metric_affected == "will_pay_probability"
    assert any(a.source == SOURCE_FUNNEL for a in out.actions)
    assert out.actions[0].priority == 1

    # Priorities are sequential and the plan is capped.
    assert [a.priority for a in out.actions] == list(range(1, len(out.actions) + 1))
    assert len(out.actions) <= MAX_ACTIONS


def test_effort_tiers_are_consistent() -> None:
    out = build_founder_action_plan(_results(), simulation_id=1, project_id=1)
    efforts = {a.metric_affected: a.effort for a in out.actions}
    assert efforts["will_pay_probability"] == EFFORT_MEDIUM
    assert efforts["onboarding_completion_rate"] == EFFORT_MEDIUM
    assert efforts["drop_off_decide"] == EFFORT_MEDIUM
    assert EFFORT_MEDIUM in efforts.values()


def test_quick_win_score_ranks_low_effort_higher_at_similar_impact() -> None:
    results = _results(include_stages=False)
    results["domain_findings"] = [
        {
            "architect_name": "ViralityArchitect",
            "cluster_id": "cluster_a",
            "cluster_name": "A",
            "metric_affected": "organic_referral_trigger_score",
            "finding": "Referral trigger is low.",
            "recommended_action": "Add a referral incentive.",
            "severity": "WARNING",
            "actual_value": 0.01,
            "healthy_benchmark": 0.05,
            "conversion_impact": 0.01,
            "affected_agent_count": 500,
        },
        {
            "architect_name": "DistributionChannelArchitect",
            "cluster_id": "cluster_b",
            "cluster_name": "B",
            "metric_affected": "distribution_accessibility_multiplier",
            "finding": "Accessibility is low.",
            "recommended_action": "Add a new distribution channel.",
            "severity": "WARNING",
            "actual_value": 0.3,
            "healthy_benchmark": 0.8,
            "conversion_impact": 0.011,
            "affected_agent_count": 600,
        },
    ]
    out = build_founder_action_plan(results, simulation_id=1, project_id=1)
    assert out.actions[0].metric_affected == "organic_referral_trigger_score"
    assert out.actions[0].effort == EFFORT_LOW
    assert out.actions[1].effort == EFFORT_HIGH


def test_missing_stages_still_builds_plan_from_findings() -> None:
    results = _results(include_stages=False)
    out = build_founder_action_plan(results, simulation_id=1, project_id=1)
    assert out.primary_bottleneck is None
    assert out.summary.total_actions == 2
    assert all(a.source == SOURCE_DOMAIN_FINDING for a in out.actions)


def test_verdict_reflects_critical_issues() -> None:
    out = build_founder_action_plan(_results(), simulation_id=1, project_id=1)
    assert out.summary.total_critical >= 1
    assert out.summary.verdict == "CRITICAL_ISSUES"
    assert out.summary.estimated_total_conversion_impact > 0.0


def test_malformed_findings_are_skipped() -> None:
    results = _results(include_findings=False, include_stages=False)
    results["domain_findings"] = [
        "not-a-dict",
        {"metric_affected": "day7_survival", "severity": "WARNING", "conversion_impact": 0.02},
        None,
    ]
    out = build_founder_action_plan(results, simulation_id=1, project_id=1)
    assert len(out.actions) == 1
    assert out.actions[0].metric_affected == "day7_survival"


def test_stage_rows_can_be_stage_aggregations() -> None:
    results = _results(include_findings=False, include_stages=False)
    results["stage_aggregations"] = [
        {"stage": "ARRIVE", "agents": 10000, "mean_drop_off_rate": 0.12},
        {"stage": "BROWSE", "agents": 8800, "mean_drop_off_rate": 0.40},
        {"stage": "CONSIDER", "agents": 5200, "mean_drop_off_rate": 0.42},
        {"stage": "DECIDE", "agents": 2100, "mean_drop_off_rate": 0.76},
        {"stage": "PURCHASE", "agents": 310, "mean_drop_off_rate": 0.0},
    ]
    out = build_founder_action_plan(results, simulation_id=1, project_id=1)
    assert out.primary_bottleneck == "DECIDE"
    assert any(a.stage == "DECIDE" for a in out.actions)

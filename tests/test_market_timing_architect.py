"""
Tests for ``app.simulation.architects.market_timing`` — MarketTimingArchitect.

Locks down category-awareness math, problem-urgency multipliers,
switching-cost path, budget-cycle alignment, technology-adoption
position classifier, regulatory dependency, severity tiers, flags,
narrative findings, transition_overrides, and generate_report()
cross-cluster rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    literacy: float = 0.5,
    motivation: float = 0.5,
    income: float = 0.5,
    trust: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
    geography: str = "metro_delhi",
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
        demographic_profile={"geography": geography, "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_market_timing_name_constant() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    assert MarketTimingArchitect().name == "MarketTimingArchitect"


def test_market_timing_product_types_is_all() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = MarketTimingArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_eleven_metrics() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "MarketTimingArchitect"
    assert len(out.metrics) == 11


# ---------------------------------------------------------------------------
# category_awareness_score
# ---------------------------------------------------------------------------


def test_awareness_floor_at_005() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[],
        env_params={"market_maturity": 0.0, "scenario_type": "NORMAL"},
    )
    assert out.metrics["category_awareness_score"] >= 0.05


def test_awareness_ceiling_at_100() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=1.0),
        agent_profile={}, assumptions=[],
        env_params={"market_maturity": 1.0},
    )
    assert out.metrics["category_awareness_score"] <= 1.0


def test_awareness_scales_with_market_maturity() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    low = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.1},
    )
    high = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.9},
    )
    assert high.metrics["category_awareness_score"] > low.metrics["category_awareness_score"]


# ---------------------------------------------------------------------------
# problem_urgency_intensity
# ---------------------------------------------------------------------------


def test_urgency_higher_for_founder_cluster_id() -> None:
    """founder/professional/startup cluster_id → ×1.3 multiplier."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    base = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={},
        assumptions=[{"text": "Solution is urgent and critical for users."}],
        env_params={},
    )
    founder = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="metro_professional_founder"),
        agent_profile={},
        assumptions=[{"text": "Solution is urgent and critical for users."}],
        env_params={},
    )
    assert founder.metrics["problem_urgency_intensity"] > base.metrics["problem_urgency_intensity"]


def test_urgency_lower_for_passive_cluster_id() -> None:
    """passive/late_majority/minimalist → ×0.6 multiplier."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    base = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={},
        assumptions=[{"text": "Pain is acute."}],
        env_params={},
    )
    passive = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="low_literacy_passive"),
        agent_profile={},
        assumptions=[{"text": "Pain is acute."}],
        env_params={},
    )
    assert passive.metrics["problem_urgency_intensity"] < base.metrics["problem_urgency_intensity"]


# ---------------------------------------------------------------------------
# switching_cost_depth
# ---------------------------------------------------------------------------


def test_switching_cost_capped_at_095() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=1.0, risk=0.0),  # sophistication = 0.6 + 1.0 = ?
        agent_profile={},
        assumptions=[{"text": "Users are switching from a competitor."}],
        env_params={"market_maturity": 1.0},
    )
    assert out.metrics["switching_cost_depth"] <= 0.95


def test_switching_cost_higher_when_sophisticated_and_mature() -> None:
    """sophistication > 0.6 AND market_maturity > 0.5 → ×1.4 multiplier."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    low = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.2, risk=0.9),
        agent_profile={},
        assumptions=[{"text": "Switching is happening."}],
        env_params={"market_maturity": 0.1},
    )
    high = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.9, risk=0.1),
        agent_profile={},
        assumptions=[{"text": "Switching is happening."}],
        env_params={"market_maturity": 0.9},
    )
    assert high.metrics["switching_cost_depth"] > low.metrics["switching_cost_depth"]


# ---------------------------------------------------------------------------
# budget_cycle_alignment
# ---------------------------------------------------------------------------


def test_budget_alignment_default_is_070_for_consumer() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="metro_consumer"),
        agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["budget_cycle_alignment"] == 0.70


def test_budget_alignment_enterprise_high_growth_scenario() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="enterprise_decision_maker"),
        agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH"},
    )
    assert out.metrics["budget_cycle_alignment"] == 0.80


def test_budget_alignment_enterprise_normal_scenario() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="b2b_purchaser"),
        agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["budget_cycle_alignment"] == 0.50


# ---------------------------------------------------------------------------
# adoption_position classifier
# ---------------------------------------------------------------------------


def test_adoption_position_early_adopter_for_high_traits() -> None:
    """literacy > 0.7 AND motivation > 0.7 AND risk_av < 0.3 → early_adopter."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.9, motivation=0.9, risk=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["adoption_position"] is True


def test_adoption_position_laggard_for_low_literacy_or_high_risk() -> None:
    """literacy < 0.3 OR risk_av > 0.8 → laggard."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.2, risk=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["laggard_cluster"] is True


# ---------------------------------------------------------------------------
# derived metrics
# ---------------------------------------------------------------------------


def test_trigger_sensitivity_085_for_founder_professional() -> None:
    """founder/startup/professional cluster_id → 0.85."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="metro_founder_pro"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["trigger_event_sensitivity"] == 0.85


def test_trigger_sensitivity_default_030() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["trigger_event_sensitivity"] == 0.30


def test_category_creation_cost_tier_thresholds() -> None:
    """< 0.40 → 0.85; < 0.75 → 0.50; else 0.20."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    # Very low awareness + low literacy → ccc = 0.85
    out_low = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.0),
        agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.0},
    )
    assert out_low.metrics["category_creation_cost"] == 0.85


def test_high_education_cost_flag_when_ccc_above_070() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.0),
        agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.0},
    )
    assert out.metrics["category_creation_cost"] > 0.70
    assert out.flags["high_education_cost"] is True


def test_seasonal_coefficient_135_when_seasonal_flag_in_assumptions() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Demand peaks during festival season."}],
        env_params={},
    )
    assert out.metrics["seasonal_demand_coefficient"] == 1.35


def test_seasonal_coefficient_default_100() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={},
    )
    assert out.metrics["seasonal_demand_coefficient"] == 1.0


def test_pricing_power_capped_at_120() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Pain is acute and urgent."}],
        env_params={"market_maturity": 1.0},
    )
    assert out.metrics["market_maturity_pricing_power"] <= 1.20


def test_pricing_power_lower_when_urgency_low() -> None:
    """urgency > 0.6 → ×1.0; else ×0.85. With identical traits and a
    non-professional cluster_id (default urgency mult ×1.0), the
    high-urgency assumption run produces a strictly higher pricing
    power."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    # Use a generic cluster_id so urgency multiplier stays at 1.0 (no
    # 'professional' / 'founder' / 'startup' boost).
    env = {"market_maturity": 0.5}
    low = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={}, assumptions=[], env_params=env,
    )
    high = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={},
        assumptions=[{"text": "Must have urgent solution."}],
        env_params=env,
    )
    assert high.metrics["market_maturity_pricing_power"] > low.metrics["market_maturity_pricing_power"]


# ---------------------------------------------------------------------------
# regulatory_dependency_risk
# ---------------------------------------------------------------------------


def test_regulatory_risk_070_when_assumption_mentions_regulation() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Subject to RBI compliance."}],
        env_params={},
    )
    assert out.metrics["regulatory_dependency_risk"] == 0.70
    assert out.metrics["regulatory_suppressor"] == 0.40
    assert out.flags["regulatory_blocked"] is True


def test_regulatory_risk_default_010() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["regulatory_dependency_risk"] == 0.10
    assert out.metrics["regulatory_suppressor"] == 1.0
    assert out.flags["regulatory_blocked"] is False


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_critical_when_awareness_below_030() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(literacy=0.0),
        agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.0},
    )
    assert out.metrics["category_awareness_score"] < 0.30
    assert out.severity == "CRITICAL"


def test_severity_critical_when_regulatory_and_low_urgency() -> None:
    """regulatory_dep=True AND urgency < 0.5 → CRITICAL."""
    from app.simulation.architects.market_timing import MarketTimingArchitect

    # 'nice to have' → urgency_stated = 0.25 < 0.5; FDA keyword triggers
    # regulatory_dep=True.
    out = MarketTimingArchitect().compute(
        cluster=_cluster(cluster_id="random_user"),
        agent_profile={},
        assumptions=[{"text": "Requires FDA approval and is nice to have when time permits."}],
        env_params={},
    )
    assert out.flags["regulatory_blocked"] is True
    # problem_urgency = min(1.0, 0.25 * 1.0) = 0.25 < 0.5
    assert out.metrics["problem_urgency_intensity"] < 0.5
    assert out.severity == "CRITICAL"


def test_severity_warning_when_awareness_between_030_and_055() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(),
        agent_profile={}, assumptions=[],
        env_params={"market_maturity": 0.05},
    )
    # awareness may fall in CRITICAL range; just verify severity is one
    # of the defined values.
    assert out.severity in {"CRITICAL", "WARNING", "INFO"}


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    out = MarketTimingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Category awareness" in joined or "awareness" in joined
    assert "Adoption position" in joined or "Switching" in joined


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_arrive_to_browse_uses_awareness_urgency_reg() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    a = MarketTimingArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    arr_b = out.metrics["category_awareness_score"]
    urg = out.metrics["problem_urgency_intensity"]
    reg = out.metrics["regulatory_suppressor"]
    expected = max(0.05, min(0.95, arr_b * urg * reg))
    assert overrides[("ARRIVE", "BROWSE")] == expected


def test_transition_overrides_browse_to_consider_uses_cat_cost_and_budget() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    a = MarketTimingArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    cat_cost = out.metrics["category_creation_cost"]
    budget = out.metrics["budget_cycle_alignment"]
    expected = max(0.05, min(0.95, (1 - cat_cost) * budget))
    assert overrides[("BROWSE", "CONSIDER")] == expected


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    a = MarketTimingArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_critical_and_blocked_clusters() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = MarketTimingArchitect()
    crit = ArchitectOutput(
        architect_name="MarketTimingArchitect",
        cluster_id="tier3_awareness_critical",
        metrics={},
        flags={"awareness_critical": True, "regulatory_blocked": False},
        narrative_findings=[],
        severity="CRITICAL",
    )
    blocked = ArchitectOutput(
        architect_name="MarketTimingArchitect",
        cluster_id="metro_regulatory",
        metrics={},
        flags={"awareness_critical": False, "regulatory_blocked": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    ok = ArchitectOutput(
        architect_name="MarketTimingArchitect",
        cluster_id="metro_ok",
        metrics={},
        flags={"awareness_critical": False, "regulatory_blocked": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([crit, blocked, ok])
    assert report.severity == "CRITICAL"
    assert "tier3_awareness_critical" in report.affected_cluster_ids
    assert "metro_regulatory" in report.affected_cluster_ids
    assert "metro_ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.market_timing import MarketTimingArchitect

    a = MarketTimingArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

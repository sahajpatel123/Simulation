"""
Tests for ``app.simulation.architects.competitive_dynamics`` —
CompetitiveDynamicsArchitect.

Locks down assumption parsing for competitor type / differentiation /
feature completion, switching-friction formula with risk-aversion and
competitor-type multipliers, feature-parity thresholds by market
maturity × sophistication, derived competitive metrics, severity
tiers, flags, narrative findings, transition_overrides, and the
generate_report() cross-cluster rollup.
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
    trust: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "metro_power_professional",
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
        demographic_profile={"geography": "metro_delhi"},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_competitive_dynamics_name_constant() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    assert CompetitiveDynamicsArchitect().name == "CompetitiveDynamicsArchitect"


def test_competitive_dynamics_product_types_is_all() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = CompetitiveDynamicsArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_ten_metrics() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "CompetitiveDynamicsArchitect"
    assert len(out.metrics) == 10


# ---------------------------------------------------------------------------
# Default behavior
# ---------------------------------------------------------------------------


def test_default_competitor_type_paid_only_when_no_assumptions() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["free_competitor_present"] is False
    assert out.flags["no_competition"] is False


def test_free_competitor_flag_for_open_source_keyword() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "There is an open source alternative."}],
        env_params={},
    )
    assert out.flags["free_competitor_present"] is True


def test_no_competition_flag_for_new_category_keyword() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "We are creating a new category with no competitor."}],
        env_params={},
    )
    assert out.flags["no_competition"] is True


# ---------------------------------------------------------------------------
# Switching friction
# ---------------------------------------------------------------------------


def test_switching_friction_capped_at_095() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=1.0), agent_profile={}, assumptions=[],
        env_params={},  # switching_cost default 0.5
    )
    assert out.metrics["incumbent_switching_friction"] <= 0.95


def test_switching_friction_higher_for_risk_averse_cluster() -> None:
    """risk_av > 0.7 → ×1.3 multiplier; default ×0.9."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    low_risk = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.3), agent_profile={},
        assumptions=[], env_params={},
    )
    high_risk = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.9), agent_profile={},
        assumptions=[], env_params={},
    )
    assert high_risk.metrics["incumbent_switching_friction"] > low_risk.metrics["incumbent_switching_friction"]


def test_switching_friction_higher_for_free_competitor() -> None:
    """competitor_type = free → ×1.5 multiplier; paid_only ×1.0."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    paid = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5), agent_profile={},
        assumptions=[], env_params={},
    )
    free = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5), agent_profile={},
        assumptions=[{"text": "Free competitor exists."}],
        env_params={},
    )
    assert free.metrics["incumbent_switching_friction"] > paid.metrics["incumbent_switching_friction"]


def test_switching_friction_lower_for_no_competition() -> None:
    """competitor_type = none → ×0.2 multiplier."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    paid = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5), agent_profile={},
        assumptions=[], env_params={},
    )
    none_ = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5), agent_profile={},
        assumptions=[{"text": "No competitor exists."}],
        env_params={},
    )
    assert none_.metrics["incumbent_switching_friction"] < paid.metrics["incumbent_switching_friction"]


# ---------------------------------------------------------------------------
# Feature parity
# ---------------------------------------------------------------------------


def test_parity_threshold_tiered_by_market_maturity() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    high = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={"market_maturity": 0.8},
    )
    mid = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={"market_maturity": 0.5},
    )
    low = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={"market_maturity": 0.1},
    )
    assert high.metrics["feature_parity_threshold"] >= mid.metrics["feature_parity_threshold"]
    assert mid.metrics["feature_parity_threshold"] >= low.metrics["feature_parity_threshold"]


def test_parity_threshold_no_competitor_lowered() -> None:
    """competitor_type == 'none' → 0.20 base (lower bar). Only applies
    when market_maturity ≤ 0.4 (so the 0.65 tier isn't picked first)."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    # Use 'new category' keyword (unambiguous for 'none' branch).
    none_comp = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "We are a new category."}],
        env_params={"market_maturity": 0.3},
    )
    paid = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[],
        env_params={"market_maturity": 0.3},
    )
    assert none_comp.flags["no_competition"] is True
    assert none_comp.metrics["feature_parity_threshold"] < paid.metrics["feature_parity_threshold"]


def test_parity_threshold_capped_at_095() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[], env_params={"market_maturity": 1.0},
    )
    assert out.metrics["feature_parity_threshold"] <= 0.95


def test_parity_met_for_feature_complete_assumption() -> None:
    """feature_completion = 0.90 (feature_complete / full featured / all_features)."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Product is feature complete and full featured."}],
        env_params={"market_maturity": 0.5},
    )
    # feature_completion 0.90 vs parity 0.65 → met.
    assert out.metrics["feature_parity_met"] == 1.0


def test_parity_not_met_for_mvp_assumption() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "MVP launch, limited features."}],
        env_params={"market_maturity": 0.5},
    )
    assert out.metrics["feature_parity_met"] == 0.0
    assert out.flags["feature_parity_not_met"] is True


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------


def test_price_undercutting_higher_for_no_competitor() -> None:
    """price_undercutting = (1 - switching_friction) * 0.6 * (...).
    No competitor → very low friction → price-undercutting pressure is
    high. Free competitor → high friction → less undercutting pressure."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    # Use lower risk so neither path hits a cap.
    no_comp = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.3), agent_profile={},
        assumptions=[{"text": "new category with no competitor."}],
        env_params={"market_maturity": 0.5},
    )
    free = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.3), agent_profile={},
        assumptions=[{"text": "free alternative exists."}],
        env_params={"market_maturity": 0.5},
    )
    assert no_comp.metrics["price_undercutting_response"] > free.metrics["price_undercutting_response"]


def test_niche_pref_higher_for_sophisticated_cluster() -> None:
    """sophistication > 0.6 → 0.75 niche_pref; else 0.35."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    low = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(literacy=0.3, risk=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    high = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(literacy=0.9, risk=0.1),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert high.metrics["niche_vs_broad_preference"] > low.metrics["niche_vs_broad_preference"]
    assert low.metrics["niche_vs_broad_preference"] == 0.35


def test_displacement_days_floor_at_three() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.05), agent_profile={},
        assumptions=[{"text": "new category with no competitor."}],
        env_params={"market_maturity": 0.5},
    )
    assert out.metrics["competitive_displacement_days"] >= 3


def test_displacement_days_shorter_for_high_urgency() -> None:
    """urgency > 0.7 → 0.5 multiplier; else 1.5."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    urgent = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5),
        agent_profile={"problem_urgency_intensity": 0.9},
        assumptions=[], env_params={},
    )
    not_urgent = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.5),
        agent_profile={"problem_urgency_intensity": 0.1},
        assumptions=[], env_params={},
    )
    assert urgent.metrics["competitive_displacement_days"] < not_urgent.metrics["competitive_displacement_days"]


def test_loss_aversion_capped_at_090() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=1.0), agent_profile={},
        assumptions=[], env_params={},
    )
    assert out.metrics["loss_aversion_magnitude"] <= 0.90


def test_brand_loyalty_capped_at_085() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(trust=1.0), agent_profile={},
        assumptions=[], env_params={"market_maturity": 0.7},
    )
    assert out.metrics["competitor_brand_loyalty_strength"] <= 0.85


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_critical_when_high_friction_and_no_parity() -> None:
    """switching_friction > 0.75 AND not feature_parity_met → CRITICAL."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.9),  # high risk → 1.3 multiplier
        agent_profile={"switching_cost_depth": 0.95},
        assumptions=[{"text": "MVP launch with limited features."}],  # low fc + free → high friction
        env_params={"market_maturity": 0.7},
    )
    # Confirm the precondition.
    if out.metrics["incumbent_switching_friction"] > 0.75 and out.metrics["feature_parity_met"] == 0.0:
        assert out.severity == "CRITICAL"


def test_severity_warning_when_friction_above_050() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.9),
        agent_profile={"switching_cost_depth": 0.95},
        assumptions=[],
        env_params={"market_maturity": 0.7},
    )
    if 0.50 < out.metrics["incumbent_switching_friction"] <= 0.75:
        assert out.severity == "WARNING"


def test_severity_info_low_friction_no_competitor() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(risk=0.1),
        agent_profile={},
        assumptions=[{"text": "new category with no competitor."}],
        env_params={"market_maturity": 0.2},
    )
    assert out.metrics["incumbent_switching_friction"] <= 0.50
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    out = CompetitiveDynamicsArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Switching friction" in joined or "friction" in joined
    assert "Displacement" in joined or "Parity" in joined


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_clamped_in_unit_interval() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    a = CompetitiveDynamicsArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    for v in overrides.values():
        assert 0.05 <= v <= 0.95


def test_transition_overrides_consider_to_decide_floor_at_015_when_parity_zero() -> None:
    """If parity_met == 0 → 0.15 floor before clamping to 0.05."""
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    a = CompetitiveDynamicsArchitect()
    out = a.compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[{"text": "MVP only, basic features."}],  # parity not met
        env_params={"market_maturity": 0.5},
    )
    overrides = a.transition_overrides(out)
    val = overrides[("CONSIDER", "DECIDE")]
    # With parity=0 and any friction < 1, (1-friction) * 0.15 ≥ 0.05 after max clamp.
    assert val >= 0.05


def test_transition_overrides_decide_to_abandon_capped_at_060() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    a = CompetitiveDynamicsArchitect()
    out = a.compute(
        cluster=_cluster(risk=1.0), agent_profile={},
        assumptions=[], env_params={},
    )
    overrides = a.transition_overrides(out)
    val = overrides[("DECIDE", "ABANDON")]
    assert val <= 0.60


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    a = CompetitiveDynamicsArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_critical_and_no_parity_clusters() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = CompetitiveDynamicsArchitect()
    crit = ArchitectOutput(
        architect_name="CompetitiveDynamicsArchitect",
        cluster_id="high_friction",
        metrics={},
        flags={"switching_friction_critical": True, "feature_parity_not_met": False},
        narrative_findings=[],
        severity="CRITICAL",
    )
    no_parity = ArchitectOutput(
        architect_name="CompetitiveDynamicsArchitect",
        cluster_id="no_parity",
        metrics={},
        flags={"switching_friction_critical": False, "feature_parity_not_met": True},
        narrative_findings=[],
        severity="WARNING",
    )
    ok = ArchitectOutput(
        architect_name="CompetitiveDynamicsArchitect",
        cluster_id="ok",
        metrics={},
        flags={"switching_friction_critical": False, "feature_parity_not_met": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([crit, no_parity, ok])
    assert report.severity == "CRITICAL"
    assert "high_friction" in report.affected_cluster_ids
    assert "no_parity" in report.affected_cluster_ids
    assert "ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.competitive_dynamics import CompetitiveDynamicsArchitect

    a = CompetitiveDynamicsArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

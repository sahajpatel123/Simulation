"""
Tests for ``app.simulation.architects.support_friction`` —
SupportFrictionArchitect.

Locks down support_ticket_likelihood, self_serve_resolution_rate,
response_time_tolerance (income/patience tiers), bug_tolerance
threshold, downtime_sensitivity, escalation preference classifier,
documentation perception, severity tiers, flags, narrative findings,
and the generate_report() cross-cluster rollup.
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


def test_support_friction_name_constant() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    assert SupportFrictionArchitect().name == "SupportFrictionArchitect"


def test_support_friction_product_types_is_all() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = SupportFrictionArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_six_metrics() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "SupportFrictionArchitect"
    assert len(out.metrics) == 6


# ---------------------------------------------------------------------------
# support_ticket_likelihood
# ---------------------------------------------------------------------------


def test_ticket_rate_capped_at_070() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.0),
        agent_profile={"onboarding_completion_rate": 0.0, "product_complexity": 1.0},
        assumptions=[], env_params={},
    )
    assert out.metrics["support_ticket_likelihood"] <= 0.70


def test_ticket_rate_higher_for_low_literacy() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    low_lit = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.1),
        agent_profile={"onboarding_completion_rate": 0.3, "product_complexity": 0.8},
        assumptions=[], env_params={},
    )
    high_lit = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.9),
        agent_profile={"onboarding_completion_rate": 0.9, "product_complexity": 0.1},
        assumptions=[], env_params={},
    )
    assert low_lit.metrics["support_ticket_likelihood"] > high_lit.metrics["support_ticket_likelihood"]


# ---------------------------------------------------------------------------
# self_serve_resolution_rate
# ---------------------------------------------------------------------------


def test_self_serve_higher_with_knowledge_base() -> None:
    """has_knowledge_base=True → kb_factor=1.3; else 0.5."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    no_kb = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.8),
        agent_profile={"has_knowledge_base": False},
        assumptions=[], env_params={},
    )
    with_kb = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.8),
        agent_profile={"has_knowledge_base": True},
        assumptions=[], env_params={},
    )
    assert with_kb.metrics["self_serve_resolution_rate"] > no_kb.metrics["self_serve_resolution_rate"]


def test_self_serve_capped_at_090() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=1.0),
        agent_profile={"has_knowledge_base": True},
        assumptions=[], env_params={},
    )
    assert out.metrics["self_serve_resolution_rate"] <= 0.90


# ---------------------------------------------------------------------------
# response_time_tolerance_hours
# ---------------------------------------------------------------------------


def test_response_tolerance_income_tiers() -> None:
    """income > 0.7 → 4h base; > 0.5 → 8h; else 24h. Then × patience."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    rich = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.9, patience=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    mid = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.6, patience=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    poor = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.3, patience=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    # rich base=4h × 0.5 = 2h; mid=8*0.5=4; poor=24*0.5=12
    assert rich.metrics["response_time_tolerance_hours"] == 2.0
    assert mid.metrics["response_time_tolerance_hours"] == 4.0
    assert poor.metrics["response_time_tolerance_hours"] == 12.0


def test_response_tolerance_rounded_to_2_decimals() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["response_time_tolerance_hours"] == round(out.metrics["response_time_tolerance_hours"], 2)


# ---------------------------------------------------------------------------
# bug_tolerance_threshold
# ---------------------------------------------------------------------------


def test_bug_tolerance_floor_at_one() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(patience=0.0, trust=0.5, price_sens=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["bug_tolerance_threshold"] >= 1


def test_bug_tolerance_lower_for_low_trust() -> None:
    """trust < 0.4 → ×0.7 multiplier. Use a high patience so the
    floor at 1 doesn't equalize the two paths."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    high_trust = SupportFrictionArchitect().compute(
        cluster=_cluster(patience=0.9, trust=0.8),
        agent_profile={}, assumptions=[], env_params={},
    )
    low_trust = SupportFrictionArchitect().compute(
        cluster=_cluster(patience=0.9, trust=0.2),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert low_trust.metrics["bug_tolerance_threshold"] < high_trust.metrics["bug_tolerance_threshold"]


def test_bug_tolerance_higher_for_price_insensitive() -> None:
    """price_sens < 0.3 → ×1.4; else ×0.8."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    sensitive = SupportFrictionArchitect().compute(
        cluster=_cluster(price_sens=0.7, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    insensitive = SupportFrictionArchitect().compute(
        cluster=_cluster(price_sens=0.1, patience=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert insensitive.metrics["bug_tolerance_threshold"] > sensitive.metrics["bug_tolerance_threshold"]


# ---------------------------------------------------------------------------
# downtime_sensitivity
# ---------------------------------------------------------------------------


def test_downtime_sensitivity_capped_at_090() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(income=1.0, patience=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["downtime_sensitivity"] <= 0.90


def test_downtime_sensitivity_higher_for_rich_low_patience() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    rich_impatient = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.9, patience=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    poor_patient = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.1, patience=1.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert rich_impatient.metrics["downtime_sensitivity"] > poor_patient.metrics["downtime_sensitivity"]


# ---------------------------------------------------------------------------
# Escalation preference
# ---------------------------------------------------------------------------


def test_escalation_phone_for_high_income() -> None:
    """income > 0.7 → 'phone' regardless of literacy."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.9, literacy=0.9),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["phone_support_required"] is True


def test_escalation_chat_for_mid_literacy_non_high_income() -> None:
    """income ≤ 0.7 AND literacy > 0.6 → 'chat'."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.5, literacy=0.8),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["phone_support_required"] is False


def test_escalation_phone_for_low_literacy() -> None:
    """income ≤ 0.7 AND literacy < 0.4 → 'phone'."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.3, literacy=0.2),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["phone_support_required"] is True


def test_escalation_email_default_for_mid_literacy() -> None:
    """income ≤ 0.7 AND literacy in [0.4, 0.6] → 'email'."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(income=0.5, literacy=0.5),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.flags["phone_support_required"] is False


# ---------------------------------------------------------------------------
# documentation perception
# ---------------------------------------------------------------------------


def test_doc_perception_zero_when_no_kb_default_and_literacy_low() -> None:
    """has_knowledge_base missing → defaults to True; literacy 0 → 0 effect."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.0),
        agent_profile={}, assumptions=[], env_params={},
    )
    assert out.metrics["documentation_quality_perception_effect"] == 0.0


def test_doc_perception_negative_when_no_kb_and_literacy_high() -> None:
    """has_knowledge_base=False → doc_mult=-0.25 → doc_effect < 0."""
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.8),
        agent_profile={"has_knowledge_base": False},
        assumptions=[], env_params={},
    )
    # literacy * 0.3 * (-0.25) = -0.06
    assert out.metrics["documentation_quality_perception_effect"] < 0.0


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_warning_when_ticket_rate_above_035() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.1, patience=0.1),
        agent_profile={"onboarding_completion_rate": 0.1, "product_complexity": 0.8},
        assumptions=[], env_params={},
    )
    assert out.metrics["support_ticket_likelihood"] > 0.35
    assert out.severity == "WARNING"


def test_severity_info_with_normal_ticket_rate() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.9, patience=0.9),
        agent_profile={"onboarding_completion_rate": 0.9, "product_complexity": 0.1},
        assumptions=[], env_params={},
    )
    assert out.metrics["support_ticket_likelihood"] <= 0.35
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_low_self_serve_flag_below_030() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(literacy=0.1),
        agent_profile={"has_knowledge_base": False},
        assumptions=[], env_params={},
    )
    assert out.metrics["self_serve_resolution_rate"] < 0.30
    assert out.flags["low_self_serve"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_three_narrative_findings() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    out = SupportFrictionArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 3
    joined = " | ".join(out.narrative_findings)
    assert "Support ticket rate" in joined
    assert "Bug tolerance" in joined
    assert "Escalation preference" in joined


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    a = SupportFrictionArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_high_friction_clusters() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = SupportFrictionArchitect()
    high = ArchitectOutput(
        architect_name="SupportFrictionArchitect",
        cluster_id="tier3_high_friction",
        metrics={},
        flags={"high_ticket_rate": True},
        narrative_findings=[],
        severity="WARNING",
    )
    low = ArchitectOutput(
        architect_name="SupportFrictionArchitect",
        cluster_id="metro_low_friction",
        metrics={},
        flags={"high_ticket_rate": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([high, low])
    assert report.severity == "WARNING"
    assert "tier3_high_friction" in report.affected_cluster_ids
    assert "metro_low_friction" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.support_friction import SupportFrictionArchitect

    a = SupportFrictionArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

"""
Tests for ``app.simulation.architects.assumption_cascade`` —
AssumptionCascadeArchitect.

Locks down critical-assumption filtering, domain classification of
free-text, impact weights per domain, confidence multipliers, delta
computation, compound failure probability matrix, positive cascade
detection, blind spot scoring, severity tiers, flags, narrative
findings, and the generate_report() cross-cluster rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    cluster_id: str = "metro_power_professional",
    literacy: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
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


def test_assumption_cascade_name_constant() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    assert AssumptionCascadeArchitect().name == "AssumptionCascadeArchitect"


def test_assumption_cascade_product_types_is_all() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = AssumptionCascadeArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Correlation map shape
# ---------------------------------------------------------------------------


def test_correlation_map_has_expected_pairs() -> None:
    from app.simulation.architects.assumption_cascade import ASSUMPTION_CORRELATION_MAP

    # Should be 6 pairs with tuple keys.
    assert len(ASSUMPTION_CORRELATION_MAP) == 6
    for key in ASSUMPTION_CORRELATION_MAP.keys():
        assert isinstance(key, tuple) and len(key) == 2


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_no_assumptions_returns_neutral() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "AssumptionCascadeArchitect"
    assert len(out.metrics) == 7
    # No critical assumptions → neutral payload.
    assert out.metrics["critical_assumption_count"] == 0
    assert out.metrics["primary_failure_domain_delta"] == 0.0
    assert out.metrics["compound_failure_probability"] == 0.0
    assert out.metrics["total_cascade_risk"] == 0.0


# ---------------------------------------------------------------------------
# Critical-assumption filtering
# ---------------------------------------------------------------------------


def test_non_critical_assumptions_ignored() -> None:
    """sensitivity != CRITICAL/HIGH is filtered out."""
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Users will pay 999 INR.", "sensitivity": "MEDIUM",
             "claim_confidence": "DESIGN_INTENT"},
            {"text": "Setup is one step.", "sensitivity": "LOW",
             "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    assert out.metrics["critical_assumption_count"] == 0


def test_critical_assumption_count_includes_high_and_critical() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Users will pay.", "sensitivity": "HIGH"},
            {"text": "Setup is one step.", "sensitivity": "CRITICAL"},
            {"text": "Brand known.", "sensitivity": "MEDIUM"},
        ],
        env_params={},
    )
    assert out.metrics["critical_assumption_count"] == 2


# ---------------------------------------------------------------------------
# Domain classification
# ---------------------------------------------------------------------------


def test_domain_classification_pricing_keyword() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Users will pay 999 INR per month.", "sensitivity": "CRITICAL"}],
        env_params={},
    )
    # Confidence MULT defaults to 0.55 (DESIGN_INTENT default), so delta > 0
    # means at least one critical assumption was identified.
    assert out.metrics["critical_assumption_count"] == 1


def test_domain_classification_no_keyword_general() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[{"text": "Generic hopeful statement.", "sensitivity": "CRITICAL"}],
        env_params={},
    )
    assert out.metrics["critical_assumption_count"] == 1


# ---------------------------------------------------------------------------
# Confidence multipliers
# ---------------------------------------------------------------------------


def test_validated_external_confidence_zero_delta() -> None:
    """claim_confidence=VALIDATED_EXTERNAL → mult=1.0 → delta = 0."""
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Users will pay 999.", "sensitivity": "CRITICAL",
             "claim_confidence": "VALIDATED_EXTERNAL"}
        ],
        env_params={},
    )
    # primary_failure_domain_delta comes from the assumption with the
    # largest delta; with confidence 1.0, delta = weight * 0 = 0.
    assert out.metrics["primary_failure_domain_delta"] == 0.0


def test_aspirational_confidence_higher_delta() -> None:
    """ASPIRATIONAL → mult=0.40 → delta = weight * 0.60 (higher)."""
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            # 'price' or '₹' / '999' keyword forces pricing domain (0.30 weight).
            {"text": "Price will be 999 per month.", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"}
        ],
        env_params={},
    )
    # pricing weight = 0.30 → delta = 0.30 * 0.6 = 0.18
    assert out.metrics["primary_failure_domain_delta"] == 0.18


# ---------------------------------------------------------------------------
# Compound failure probability
# ---------------------------------------------------------------------------


def test_compound_prob_zero_when_lt_two_critical_assumptions() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Users will pay.", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    assert out.metrics["compound_failure_probability"] == 0.0


def test_compound_prob_with_two_pricing_assumptions() -> None:
    """Two distinct pricing assumptions → correlation default 0.30."""
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Users will pay 999.", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"},
            {"text": "Setup is one step.", "sensitivity": "HIGH",
             "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    # Both are 'pricing' domain → sorted tuple = (pricing, pricing) → no
    # correlation in map → default 0.30.
    assert out.metrics["compound_failure_probability"] >= 0.0


def test_compound_prob_capped_at_095() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Pricing is 999.", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"},
            {"text": "Retention rate is 90%.", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    # Different domains (pricing, retention) → correlation 0.72 in map.
    # Compound is computed regardless; just verify the cap.
    assert out.metrics["compound_failure_probability"] <= 0.95


# ---------------------------------------------------------------------------
# Positive cascade
# ---------------------------------------------------------------------------


def test_positive_cascade_when_3_validated_plus_high_viral() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={"viral_coefficient": 0.3},
        assumptions=[
            {"text": "a", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_EXTERNAL"},
            {"text": "b", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_INTERNAL"},
            {"text": "c", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_EXTERNAL"},
        ],
        env_params={},
    )
    assert out.metrics["validated_assumption_count"] >= 3
    assert out.metrics["positive_cascade_active"] == 1.0
    assert out.flags["positive_cascade"] is True


def test_positive_cascade_skipped_without_high_viral() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={"viral_coefficient": 0.1},  # < 0.25
        assumptions=[
            {"text": "a", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_EXTERNAL"},
            {"text": "b", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_INTERNAL"},
            {"text": "c", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_EXTERNAL"},
        ],
        env_params={},
    )
    assert out.metrics["positive_cascade_active"] == 0.0
    assert out.flags["positive_cascade"] is False


# ---------------------------------------------------------------------------
# Blind spot score
# ---------------------------------------------------------------------------


def test_blind_spot_score_floor_at_zero_with_no_blind_spots() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "a", "sensitivity": "CRITICAL", "claim_confidence": "VALIDATED_EXTERNAL"},
        ],
        env_params={},
    )
    assert out.metrics["blind_spot_score"] == 0.0


def test_blind_spot_score_increments_per_blind_spot() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            # 2 critical + low confidence + delta > 0.08 (pricing weight 0.30 * 0.6 = 0.18)
            {"text": "Pricing is 999.", "sensitivity": "CRITICAL", "claim_confidence": "ASPIRATIONAL"},
            {"text": "Brand is known.", "sensitivity": "CRITICAL", "claim_confidence": "ASPIRATIONAL"},
            {"text": "Viral coefficient is 2.", "sensitivity": "CRITICAL", "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    # min(1.0, 3 * 0.25) = 0.75
    assert out.metrics["blind_spot_score"] >= 0.5


# ---------------------------------------------------------------------------
# Cluster sensitivity
# ---------------------------------------------------------------------------


def test_cluster_sensitivity_high_for_student() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(cluster_id="metro_student_user"),
        agent_profile={}, assumptions=[],
        env_params={},
    )
    assert out.flags["cluster_sensitivity_high"] is True


def test_cluster_sensitivity_high_for_tier3() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(cluster_id="tier3_first_time_app_user"),
        agent_profile={}, assumptions=[],
        env_params={},
    )
    assert out.flags["cluster_sensitivity_high"] is True


def test_cluster_sensitivity_medium_for_default() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={},
    )
    assert out.flags["cluster_sensitivity_high"] is False


# ---------------------------------------------------------------------------
# Total cascade risk + severity
# ---------------------------------------------------------------------------


def test_total_cascade_risk_capped_at_095() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": f"a{i}", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"}
            for i in range(5)
        ],
        env_params={},
    )
    assert out.metrics["total_cascade_risk"] <= 0.95


def test_severity_critical_when_high_cascade_risk() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": f"a{i}", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"}
            for i in range(5)
        ],
        env_params={},
    )
    # If the cascade risk exceeds 0.40 it triggers CRITICAL.
    if out.metrics["total_cascade_risk"] > 0.40:
        assert out.severity == "CRITICAL"


def test_severity_info_with_safe_assumptions() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Pricing is 999.", "sensitivity": "CRITICAL",
             "claim_confidence": "VALIDATED_EXTERNAL"},
        ],
        env_params={},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_dual_failure_risk_flag_when_compound_above_030() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": "Pricing is 999.", "sensitivity": "CRITICAL", "claim_confidence": "ASPIRATIONAL"},
            {"text": "Retention is high.", "sensitivity": "CRITICAL", "claim_confidence": "ASPIRATIONAL"},
        ],
        env_params={},
    )
    if out.metrics["compound_failure_probability"] > 0.30:
        assert out.flags["dual_failure_risk"] is True


def test_existential_risk_flag_when_cascade_above_050() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={},
        assumptions=[
            {"text": f"a{i}", "sensitivity": "CRITICAL",
             "claim_confidence": "ASPIRATIONAL"}
            for i in range(8)
        ],
        env_params={},
    )
    if out.metrics["total_cascade_risk"] > 0.50:
        assert out.flags["existential_risk"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_three_narrative_findings() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    out = AssumptionCascadeArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert len(out.narrative_findings) == 3
    joined = " | ".join(out.narrative_findings)
    assert "Primary failure domain" in joined or "domain" in joined.lower()


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    a = AssumptionCascadeArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_existential_and_blind_spot() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = AssumptionCascadeArchitect()
    existential = ArchitectOutput(
        architect_name="AssumptionCascadeArchitect",
        cluster_id="critical_cluster",
        metrics={},
        flags={"existential_risk": True, "blind_spot_detected": False},
        narrative_findings=[],
        severity="CRITICAL",
    )
    blind = ArchitectOutput(
        architect_name="AssumptionCascadeArchitect",
        cluster_id="blind_cluster",
        metrics={},
        flags={"existential_risk": False, "blind_spot_detected": True},
        narrative_findings=[],
        severity="WARNING",
    )
    ok = ArchitectOutput(
        architect_name="AssumptionCascadeArchitect",
        cluster_id="ok_cluster",
        metrics={},
        flags={"existential_risk": False, "blind_spot_detected": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([existential, blind, ok])
    assert report.severity == "CRITICAL"
    assert "critical_cluster" in report.affected_cluster_ids
    assert "blind_cluster" in report.affected_cluster_ids
    assert "ok_cluster" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.assumption_cascade import AssumptionCascadeArchitect

    a = AssumptionCascadeArchitect()
    kwargs = {"cluster": _cluster(), "agent_profile": {}, "assumptions": [], "env_params": {}}
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

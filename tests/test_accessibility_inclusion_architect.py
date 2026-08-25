"""
Tests for ``app.simulation.architects.accessibility_inclusion`` —
AccessibilityInclusionArchitect.

Locks down inclusion signal detection (disability/language/age/literacy),
negation- and intent-aware evidence handling, barrier modelling, severity
tiers, flags, narrative findings, Markov transition overrides, and the
cross-cluster generate_report() rollup — plus conductor and calibration
registration so the new domain actually surfaces as an accountability
finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    patience: float = 0.5,
    age_bracket: str = "25-35",
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
            "motivation": 0.5,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": patience,
            "social_orientation": 0.5,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["consumer_app"],
        demographic_profile={"geography": "metro", "age_bracket": age_bracket},
    )


def _compute(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    patience: float = 0.5,
    age_bracket: str = "25-35",
    assumptions: list[Any] | None = None,
    product_type: str = "saas",
) -> Any:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    return AccessibilityInclusionArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            income=income,
            price_sens=price_sens,
            patience=patience,
            age_bracket=age_bracket,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params={"product_type": product_type},
    )


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    assert architect.name == "AccessibilityInclusionArchitect"
    # Empty list = active for every product type.
    assert architect.product_types == []


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "AccessibilityInclusionArchitect"
    assert len(out.metrics) == 8
    assert out.metrics["accessibility_gap"] == 0.05
    assert out.metrics["funnel_suppressor"] == 1.0
    assert out.metrics["inclusive_advantage_lift"] == 0.0
    assert abs(out.metrics["accessibility_credibility"] - 0.955) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    out = _compute()
    assert architect.transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Disability accessibility
# ---------------------------------------------------------------------------


def test_disability_assumption_raises_gap_and_barrier() -> None:
    out = _compute(
        literacy=0.15,
        risk=0.9,
        assumptions=[{"text": "Screen reader users are a target segment"}],
    )
    assert out.metrics["accessibility_gap"] == 0.30
    assert out.metrics["disability_barrier"] > 0.15
    assert out.metrics["funnel_suppressor"] < 1.0
    assert abs(out.metrics["accessibility_credibility"] - 0.73) < 1e-9
    assert out.metrics["inclusive_signal_strength"] == 0.25


def test_accessibility_blocker_on_low_literacy_risk_averse_senior_cluster() -> None:
    out = _compute(
        literacy=0.15,
        risk=0.9,
        age_bracket="60-75",
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
        ],
    )
    assert out.metrics["accessibility_gap"] == 0.55
    assert out.metrics["disability_barrier"] >= 0.30
    assert out.flags["accessibility_blocker"] is True
    assert out.flags["inclusive_advantage"] is False
    assert out.severity == "CRITICAL"


def test_evidence_clears_blocker_and_raises_credibility() -> None:
    out = _compute(
        literacy=0.15,
        risk=0.9,
        age_bracket="60-75",
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
            {"text": "WCAG 2.1 AA compliant and captioned"},
        ],
    )
    assert out.metrics["accessibility_credibility"] == 1.0
    assert out.flags["accessibility_blocker"] is False
    assert out.flags["inclusive_advantage"] is True
    assert out.metrics["inclusive_advantage_lift"] > 0.0
    assert out.metrics["accessibility_gap"] < 0.30
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Negation- and intent-aware evidence detection
# ---------------------------------------------------------------------------


def test_negative_compliance_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We are not WCAG compliant yet"}],
    )
    assert out.metrics["accessibility_gap"] == 0.30
    assert out.metrics["accessibility_credibility"] < 1.0
    assert out.flags["inclusive_advantage"] is False
    assert out.metrics["inclusive_advantage_lift"] == 0.0


def test_intent_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We plan to add WCAG compliance and captions next quarter"}],
    )
    assert out.metrics["accessibility_credibility"] < 1.0
    assert out.flags["inclusive_advantage"] is False
    assert out.metrics["inclusive_advantage_lift"] == 0.0


def test_contracted_negations_are_not_evidence() -> None:
    for text in (
        "We aren't WCAG compliant yet",
        "The app doesn't have screen reader support",
        "We haven't captioned our videos",
        "We won't ship captioned videos this quarter",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["accessibility_credibility"] < 1.0, text
        assert out.flags["inclusive_advantage"] is False, text


def test_discourse_negation_does_not_void_evidence() -> None:
    for text in (
        "No, our app is captioned and WCAG compliant",
        "No. Our app is captioned and WCAG compliant",
        "Not only is the app captioned, it is also WCAG compliant",
        "No doubt our app is captioned",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["accessibility_credibility"] == 1.0, text
        assert out.flags["inclusive_advantage"] is True, text


def test_unrelated_intent_after_evidence_does_not_void_it() -> None:
    out = _compute(
        assumptions=[
            {"text": "We have captioned videos and will add translation support"},
        ]
    )
    assert out.metrics["accessibility_credibility"] == 1.0
    assert out.flags["inclusive_advantage"] is True


def test_after_markers_that_qualify_the_phrase_are_gaps() -> None:
    for text in (
        "An accessibility audit is scheduled for next quarter",
        "WCAG compliance is on our roadmap",
        "Translation support is planned for Q3",
        "WCAG status unclear",
        "captioned videos no longer available",
        "WCAG compliance to be completed by Q3",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["accessibility_credibility"] < 1.0, text
        assert out.flags["inclusive_advantage"] is False, text


def test_connectivity_keeps_unrelated_plan_from_voiding_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We have a plan and the app is captioned"}],
    )
    assert out.metrics["accessibility_credibility"] == 1.0
    assert out.flags["inclusive_advantage"] is True


def test_plan_to_make_phrase_is_a_gap() -> None:
    out = _compute(
        assumptions=[{"text": "We plan to make the app WCAG compliant"}],
    )
    assert out.metrics["accessibility_credibility"] < 1.0
    assert out.flags["inclusive_advantage"] is False


# ---------------------------------------------------------------------------
# Language and age barriers
# ---------------------------------------------------------------------------


def test_language_gap_for_senior_low_literacy_consumer_app() -> None:
    out = _compute(
        literacy=0.1,
        age_bracket="60-75",
        product_type="consumer_app",
        assumptions=[{"text": "Users speak regional languages like Tamil and Hindi"}],
    )
    assert out.metrics["language_barrier"] >= 0.25
    assert out.flags["language_gap"] is True
    assert out.flags["accessibility_blocker"] is False
    assert out.severity == "WARNING"


def test_senior_friction_flag_with_age_and_literacy_signals() -> None:
    out = _compute(
        literacy=0.15,
        age_bracket="60-75",
        assumptions=[
            {"text": "Elderly users are a key audience"},
            {"text": "Low digital literacy users need step-by-step guidance"},
        ],
    )
    assert out.metrics["age_friction"] >= 0.35
    assert out.flags["senior_friction"] is True
    assert out.flags["accessibility_blocker"] is False
    assert out.severity == "WARNING"


def test_english_only_counts_as_language_signal() -> None:
    out = _compute(
        product_type="consumer_app",
        assumptions=[{"text": "The app is English only"}],
    )
    assert out.metrics["accessibility_gap"] == 0.30
    assert out.metrics["inclusive_signal_strength"] == 0.25


# ---------------------------------------------------------------------------
# Malformed inputs
# ---------------------------------------------------------------------------


def test_compute_handles_malformed_traits_and_missing_assumptions() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    out = architect.compute(
        cluster=_cluster(),
        agent_profile={
            "income_level": "high",
            "digital_literacy": None,
            "risk_aversion": 3.0,
        },
        assumptions=None,
        env_params={},
    )
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert out.severity == "INFO"
    assert not any(out.flags.values())


def test_compute_handles_plain_string_assumptions() -> None:
    out = _compute(
        assumptions=["WCAG compliant app with captions"],
    )
    assert out.metrics["accessibility_credibility"] == 1.0
    assert out.flags["inclusive_advantage"] is True


def test_age_seniority_helper() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        _age_seniority,
    )

    assert _age_seniority({"age_bracket": "60-75"}) == 1.0
    assert _age_seniority({"age_bracket": "35-55"}) == 0.6
    assert _age_seniority({"age_bracket": "18-25"}) == 0.0
    assert _age_seniority(None) == 0.0
    assert _age_seniority({}) == 0.0
    assert _age_seniority({"age_bracket": "unknown"}) == 0.0


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_active_only_with_gap_or_evidence() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    neutral = _compute()
    assert architect.transition_overrides(neutral) == {}

    exposed = _compute(
        literacy=0.15,
        risk=0.9,
        age_bracket="60-75",
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
        ],
    )
    overrides = architect.transition_overrides(exposed)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert overrides[("BROWSE", "CONSIDER")] < 1.0
    assert ("DECIDE", "PURCHASE") not in overrides


def test_evidence_softens_suppressor_and_adds_purchase_lift() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    bare = _compute(
        literacy=0.15,
        risk=0.9,
        age_bracket="60-75",
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
        ],
    )
    evidenced = _compute(
        literacy=0.15,
        risk=0.9,
        age_bracket="60-75",
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
            {"text": "WCAG 2.1 AA compliant and captioned"},
        ],
    )
    bare_overrides = architect.transition_overrides(bare)
    evidenced_overrides = architect.transition_overrides(evidenced)
    assert (
        evidenced_overrides[("BROWSE", "CONSIDER")]
        > bare_overrides[("BROWSE", "CONSIDER")]
    )
    assert evidenced_overrides[("DECIDE", "PURCHASE")] > 1.0


def test_transition_overrides_skip_suppression_when_suppressor_is_one() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    architect = AccessibilityInclusionArchitect()
    # Perfectly literate, risk-tolerant, young, patient cluster: the gap is
    # active but the funnel suppressor rounds to 1.0, so no suppression
    # multiplier (which would otherwise shave a tiny bit off conversion).
    gap_only = _compute(
        literacy=1.0,
        risk=0.0,
        patience=1.0,
        assumptions=[{"text": "Screen reader users are a target segment"}],
    )
    assert gap_only.metrics["accessibility_gap"] == 0.30
    assert gap_only.metrics["funnel_suppressor"] == 1.0
    assert architect.transition_overrides(gap_only) == {}

    evidenced = _compute(
        literacy=1.0,
        risk=0.0,
        patience=1.0,
        assumptions=[{"text": "WCAG compliant and captioned"}],
    )
    assert evidenced.metrics["funnel_suppressor"] == 1.0
    overrides = architect.transition_overrides(evidenced)
    assert ("BROWSE", "CONSIDER") not in overrides
    assert ("CONSIDER", "DECIDE") not in overrides
    assert overrides[("DECIDE", "PURCHASE")] > 1.0


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )

    report = AccessibilityInclusionArchitect().generate_report([])
    assert report.architect_name == "AccessibilityInclusionArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.accessibility_inclusion import (
        AccessibilityInclusionArchitect,
    )
    from app.simulation.architects.base import ArchitectOutput

    architect = AccessibilityInclusionArchitect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="tier3_first_time_app_user",
        metrics={},
        flags={"accessibility_blocker": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="senior_citizen_cluster",
        metrics={},
        flags={"language_gap": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {
        "tier3_first_time_app_user",
        "senior_citizen_cluster",
    }
    assert report.conversion_impact > 0.0


# ---------------------------------------------------------------------------
# Conductor + calibration integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "An accessible consumer app for older users",
            "average_order_value": 499,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "Screen reader users and deaf users need captions"},
            {"text": "Elderly users need large text"},
        ],
        product_type=ProductType.CONSUMER_APP,
    )
    assert "AccessibilityInclusionArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "AccessibilityInclusionArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "AccessibilityInclusionArchitect"
        for finding in findings
    )


def test_registry_includes_new_architect_in_every_stack() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import ARCHITECT_STACKS

    registry = build_architect_registry()
    assert "AccessibilityInclusionArchitect" in registry
    for stack in ARCHITECT_STACKS.values():
        assert "AccessibilityInclusionArchitect" in stack
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "AccessibilityInclusionArchitect" in ALL_ARCHITECT_NAMES

"""
Tests for ``app.simulation.architects.behavioral_economics`` —
BehavioralEconomicsArchitect.

Locks down decision-heuristic evidence extraction (risk reversal, social
proof, choice simplicity/overload, scarcity, default bias, anchoring —
negation-aware), per-cluster bias modelling, Markov overrides at
BROWSE→CONSIDER / CONSIDER→DECIDE / DECIDE→PURCHASE, the cross-cluster
report, and conductor / calibration / specificity / accountability
registration so the domain surfaces as a founder finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    risk_aversion: float = 0.5,
    trust: float = 0.5,
    digital_literacy: float = 0.5,
    social_orientation: float = 0.5,
    price_sensitivity: float = 0.5,
    patience_score: float = 0.5,
    cluster_id: str = "test_cluster",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    traits = {
        "income_level": 0.5,
        "digital_literacy": digital_literacy,
        "motivation": 0.5,
        "trust": trust,
        "price_sensitivity": price_sensitivity,
        "risk_aversion": risk_aversion,
        "patience_score": patience_score,
        "social_orientation": social_orientation,
    }
    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.03,
        base_traits=traits,
        trait_variance={key: 0.05 for key in traits},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={"geography": "metro", "age_bracket": "25-35"},
    )


def _compute(
    *,
    risk_aversion: float = 0.5,
    trust: float = 0.5,
    digital_literacy: float = 0.5,
    social_orientation: float = 0.5,
    price_sensitivity: float = 0.5,
    patience_score: float = 0.5,
    cluster_id: str = "test_cluster",
    assumptions: list[Any] | None = None,
    description: str = "",
    product_type: str = "saas",
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.behavioral_economics import (
        BehavioralEconomicsArchitect,
    )

    if env_params is not None:
        params = dict(env_params)
        params.setdefault("product_type", product_type)
    else:
        params: dict[str, Any] = {"product_type": product_type}
        if description:
            params["description"] = description
    return BehavioralEconomicsArchitect().compute(
        cluster=_cluster(
            risk_aversion=risk_aversion,
            trust=trust,
            digital_literacy=digital_literacy,
            social_orientation=social_orientation,
            price_sensitivity=price_sensitivity,
            patience_score=patience_score,
            cluster_id=cluster_id,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.behavioral_economics import (
        BehavioralEconomicsArchitect,
    )

    return BehavioralEconomicsArchitect()


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types_are_universal() -> None:
    architect = _architect()
    assert architect.name == "BehavioralEconomicsArchitect"
    assert architect.product_types == []


def test_baseline_compute_is_neutral_when_pitch_has_no_behavioural_levers() -> None:
    out = _compute(description="A simple task tracker for small teams.")
    assert out.architect_name == "BehavioralEconomicsArchitect"
    assert len(out.metrics) == 12
    assert out.metrics["risk_reversal_evidence"] == 0.0
    assert out.metrics["social_proof_evidence"] == 0.0
    assert out.metrics["behavioral_funnel_suppressor"] == 1.0
    assert out.metrics["anchoring_effectiveness"] == 0.0
    assert out.flags["behavioral_suppression_active"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_null_and_blank_evidence_is_neutral() -> None:
    out = _compute(
        env_params={"product_type": "saas", "description": None},
        assumptions=[None, {"text": None}, {"text": ""}, {"text": "   "}],
    )
    assert out.metrics["risk_reversal_evidence"] == 0.0
    assert out.metrics["social_proof_evidence"] == 0.0
    assert out.metrics["behavioral_funnel_suppressor"] == 1.0
    assert out.severity == "INFO"


def test_duplicate_pitch_texts_are_counted_once() -> None:
    from app.simulation.architects.behavioral_economics import _collect_texts

    pitch = (
        "Our app offers a 30-day money-back guarantee and a free trial "
        "with 12,000 users."
    )
    assert _collect_texts(
        [{"text": pitch}],
        {"description": pitch},
    ) == [pitch.lower()]

    once = _compute(description=pitch)
    twice = _compute(assumptions=[{"text": pitch}], description=pitch)
    assert twice.metrics == once.metrics


# ---------------------------------------------------------------------------
# Evidence extraction (negation-aware)
# ---------------------------------------------------------------------------


def test_risk_reversal_evidence_covers_four_classes() -> None:
    out = _compute(
        description=(
            "30-day money-back guarantee, free trial, refunds with 30-day "
            "returns and cancel anytime."
        )
    )
    assert out.metrics["risk_reversal_evidence"] == 0.9
    assert out.metrics["perceived_purchase_risk"] < 0.3
    assert out.flags["risk_reversal_missing"] is False
    assert out.metrics["behavioral_funnel_suppressor"] == 1.0


def test_negated_risk_reversal_is_a_gap_not_evidence() -> None:
    out = _compute(
        risk_aversion=0.9,
        trust=0.2,
        description=(
            "No money-back guarantee, no free trial, and refunds are "
            "not available."
        ),
    )
    assert out.metrics["risk_reversal_evidence"] == 0.0
    assert out.flags["risk_reversal_missing"] is True
    assert out.flags["behavioral_suppression_active"] is True
    assert out.severity == "WARNING"


def test_risk_reversal_missing_only_for_risk_averse_low_trust_clusters() -> None:
    cautious = _compute(
        risk_aversion=0.9,
        trust=0.2,
        description="A simple task tracker for small teams.",
    )
    confident = _compute(
        risk_aversion=0.2,
        trust=0.9,
        description="A simple task tracker for small teams.",
    )
    assert cautious.flags["risk_reversal_missing"] is True
    assert confident.flags["risk_reversal_missing"] is False
    assert (
        cautious.metrics["behavioral_funnel_suppressor"]
        < confident.metrics["behavioral_funnel_suppressor"]
    )


def test_social_proof_deficit_only_for_high_need_clusters() -> None:
    no_proof = _compute(
        social_orientation=0.9,
        trust=0.2,
        description="A simple task tracker for small teams.",
    )
    with_proof = _compute(
        social_orientation=0.9,
        trust=0.2,
        description=(
            "Trusted by 12,000 users with a 4.8 rating, case studies "
            "and press coverage."
        ),
    )
    assert no_proof.flags["social_proof_deficit"] is True
    assert with_proof.metrics["social_proof_evidence"] == 0.9
    assert with_proof.flags["social_proof_deficit"] is False
    assert (
        with_proof.metrics["social_proof_coverage"]
        > no_proof.metrics["social_proof_coverage"]
    )


def test_choice_overload_activates_for_complex_pitches_and_low_literacy() -> None:
    out = _compute(
        risk_aversion=0.3,
        trust=0.8,
        digital_literacy=0.2,
        patience_score=0.2,
        description=(
            "Choose from 12 plans with many add-ons, bundles and "
            "configurable options."
        ),
    )
    assert out.metrics["choice_overload_risk"] >= 0.55
    assert out.flags["choice_overload_active"] is True
    assert out.metrics["choice_simplicity_evidence"] < 0.4
    assert out.metrics["behavioral_funnel_suppressor"] < 1.0


def test_scarcity_backfires_only_for_risk_averse_low_trust_clusters() -> None:
    suspicious = _compute(
        risk_aversion=0.8,
        trust=0.2,
        description="Limited-time launch offer, while supplies last.",
    )
    confident = _compute(
        risk_aversion=0.3,
        trust=0.8,
        description="Limited-time launch offer, while supplies last.",
    )
    assert suspicious.flags["scarcity_backfire_risk"] is True
    assert confident.flags["scarcity_backfire_risk"] is False
    assert (
        suspicious.metrics["behavioral_funnel_suppressor"]
        < confident.metrics["behavioral_funnel_suppressor"]
    )


def test_default_bias_exposure_flags_auto_renew_pitches() -> None:
    out = _compute(
        digital_literacy=0.2,
        description="Auto-renew is pre-selected and the trial converts "
        "automatically.",
    )
    assert out.metrics["default_bias_exposure"] >= 0.55
    assert out.flags["default_bias_concern"] is True
    assert out.metrics["behavioral_funnel_suppressor"] < 1.0


def test_anchoring_effectiveness_requires_an_anchor() -> None:
    anchored = _compute(
        price_sensitivity=0.9,
        description="Was ₹999, now ₹499 — save 50%.",
    )
    unanchored = _compute(
        price_sensitivity=0.9,
        description="A simple task tracker for small teams.",
    )
    assert anchored.metrics["anchoring_effectiveness"] > 0.5
    assert unanchored.metrics["anchoring_effectiveness"] == 0.0


def test_trait_sensitivity_drives_loss_aversion_and_social_weight() -> None:
    cautious = _compute(risk_aversion=0.9, trust=0.1)
    confident = _compute(risk_aversion=0.1, trust=0.9)
    assert (
        cautious.metrics["loss_aversion_sensitivity"]
        > confident.metrics["loss_aversion_sensitivity"]
    )
    assert (
        cautious.metrics["perceived_purchase_risk"]
        > confident.metrics["perceived_purchase_risk"]
    )

    social = _compute(social_orientation=0.9, trust=0.2)
    introvert = _compute(social_orientation=0.1, trust=0.9)
    assert (
        social.metrics["social_proof_weight"]
        > introvert.metrics["social_proof_weight"]
    )


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_only_when_behavioural_signal_present() -> None:
    neutral = _compute(description="A simple task tracker for small teams.")
    suppressed = _compute(
        risk_aversion=0.9,
        trust=0.2,
        digital_literacy=0.2,
        description=(
            "No money-back guarantee, no free trial, choose from 12 plans "
            "with add-ons, limited-time launch offer, auto-renew "
            "pre-selected."
        ),
    )
    assert _architect().transition_overrides(neutral) == {}
    overrides = _architect().transition_overrides(suppressed)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("DECIDE", "PURCHASE")] == suppressed.metrics[
        "behavioral_funnel_suppressor"
    ]
    assert 0.55 <= overrides[("DECIDE", "PURCHASE")] <= 0.999


# ---------------------------------------------------------------------------
# Cross-cluster report
# ---------------------------------------------------------------------------


def test_generate_report_handles_empty_outputs() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "BehavioralEconomicsArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"


def test_generate_report_aggregates_affected_clusters_and_dominant_issue() -> None:
    risk = _compute(
        risk_aversion=0.9,
        trust=0.1,
        social_orientation=0.1,
        cluster_id="risk_cluster",
        description="No money-back guarantee and no free trial.",
    )
    overload = _compute(
        risk_aversion=0.3,
        trust=0.8,
        digital_literacy=0.2,
        cluster_id="overload_cluster",
        description="Choose from 12 plans with many add-ons.",
    )
    proof = _compute(
        social_orientation=0.9,
        trust=0.2,
        cluster_id="proof_cluster",
        description="A simple task tracker for small teams.",
    )
    report = _architect().generate_report([risk, overload, proof])
    assert set(report.affected_cluster_ids) == {
        "risk_cluster",
        "overload_cluster",
        "proof_cluster",
    }
    assert 0.0 < report.population_fraction <= 1.0
    assert report.conversion_impact > 0.0
    assert "money-back" in report.recommended_action.lower()


def test_generate_report_critical_when_many_clusters_lack_risk_reversal() -> None:
    outputs = [
        _compute(
            risk_aversion=0.9,
            trust=0.1,
            cluster_id=f"risk_cluster_{i}",
            description="No money-back guarantee and no free trial.",
        )
        for i in range(3)
    ]
    report = _architect().generate_report(outputs)
    assert report.severity == "CRITICAL"
    assert len(report.affected_cluster_ids) == 3


# ---------------------------------------------------------------------------
# Conductor + calibration + specificity + accountability integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    pitch = (
        "Choose from 12 plans with many add-ons and bundles. "
        "Auto-renew is pre-selected by default. Limited-time launch offer. "
        "No money-back guarantee and no free trial."
    )
    result = Conductor().run(
        agents=[],
        env_params={"description": pitch, "average_order_value": 999},
        assumptions=[],
        product_type=ProductType.SAAS,
    )
    assert "BehavioralEconomicsArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "BehavioralEconomicsArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "BehavioralEconomicsArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_every_product_stack() -> None:
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
        _build_architect_registry,
    )

    registry = _build_architect_registry()
    assert "BehavioralEconomicsArchitect" in registry
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert "BehavioralEconomicsArchitect" in stack
        assert stack[0] == "MarketTimingArchitect"
        assert stack[1] == "CompetitiveDynamicsArchitect"
        assert stack[2] == "MessagingClarityArchitect"
        assert stack[3] == "BehavioralEconomicsArchitect"
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration_and_specificity_rules() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.scored_assumption import SPECIFICITY_RULES

    assert "BehavioralEconomicsArchitect" in ALL_ARCHITECT_NAMES
    assert "BehavioralEconomicsArchitect" in SPECIFICITY_RULES


def test_specificity_scores_behavioural_claims() -> None:
    from app.simulation.scored_assumption import _score_specificity

    assert _score_specificity(
        "BehavioralEconomicsArchitect",
        "Our app gives a 30-day money-back guarantee to 1 million users "
        "on one plan.",
    ) == 1.0
    assert _score_specificity(
        "BehavioralEconomicsArchitect",
        "We offer free trials and money-back guarantees.",
    ) == 0.6
    assert _score_specificity(
        "BehavioralEconomicsArchitect",
        "Simple, easy and risk-free",
    ) == 0.2
    assert _score_specificity(
        "BehavioralEconomicsArchitect",
        "We track productivity for teams",
    ) == 0.0


def test_specificity_denied_behavioural_levers_score_zero() -> None:
    from app.simulation.scored_assumption import _score_specificity

    for claim in (
        "No money-back guarantee and no free trial",
        "We do not have reviews or case studies yet",
        "There is no auto-renew or pre-selected plan",
    ):
        assert _score_specificity(
            "BehavioralEconomicsArchitect", claim
        ) == 0.0, claim


def test_accountability_benchmarks_cover_behavioural_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "loss_aversion_sensitivity",
        "perceived_purchase_risk",
        "social_proof_coverage",
        "choice_simplicity_evidence",
        "choice_overload_risk",
        "default_bias_exposure",
        "behavioral_funnel_suppressor",
    ):
        assert metric in benchmarks, metric
        assert metric in AccountabilityEngine.FINDING_TEMPLATES, metric
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS, metric
    for metric in (
        "loss_aversion_sensitivity",
        "perceived_purchase_risk",
        "choice_overload_risk",
        "default_bias_exposure",
    ):
        assert metric in AccountabilityEngine.LOWER_IS_BETTER, metric

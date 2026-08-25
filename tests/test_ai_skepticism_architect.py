"""
Tests for ``app.simulation.architects.ai_skepticism`` —
AISkepticismArchitect.

Locks down AI-presence extraction (negation- and exclusion-aware), AI
risk-exposure and trust-mitigation detection, per-cluster skepticism
modelling, Markov overrides at DECIDE→PURCHASE, the cross-cluster report,
and conductor / calibration / accountability registration so the domain
surfaces as a founder finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    trust: float = 0.5,
    risk_aversion: float = 0.5,
    digital_literacy: float = 0.5,
    patience_score: float = 0.5,
    age_bracket: str = "25-35",
    cluster_id: str = "test_cluster",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.03,
        base_traits={
            "income_level": 0.5,
            "digital_literacy": digital_literacy,
            "motivation": 0.5,
            "trust": trust,
            "price_sensitivity": 0.5,
            "risk_aversion": risk_aversion,
            "patience_score": patience_score,
            "social_orientation": 0.5,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={
            "geography": "metro",
            "age_bracket": age_bracket,
        },
    )


def _compute(
    *,
    trust: float = 0.5,
    risk_aversion: float = 0.5,
    digital_literacy: float = 0.5,
    patience_score: float = 0.5,
    age_bracket: str = "25-35",
    cluster_id: str = "test_cluster",
    assumptions: list[Any] | None = None,
    description: str = "",
    product_type: str = "saas",
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.ai_skepticism import AISkepticismArchitect

    if env_params is not None:
        params = dict(env_params)
        params.setdefault("product_type", product_type)
    else:
        params: dict[str, Any] = {"product_type": product_type}
        if description:
            params["description"] = description
    return AISkepticismArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk_aversion=risk_aversion,
            digital_literacy=digital_literacy,
            patience_score=patience_score,
            age_bracket=age_bracket,
            cluster_id=cluster_id,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.ai_skepticism import AISkepticismArchitect

    return AISkepticismArchitect()


_RISKY_PITCH = (
    "Our AI chatbot is fully automated with no human oversight and it "
    "trains on your data."
)
_MITIGATED_PITCH = (
    "Our AI chatbot uses human-in-the-loop review, fact-checked answers "
    "and user opt-outs; processing stays on-device."
)


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "AISkepticismArchitect"
    assert architect.product_types == []


def test_baseline_compute_is_neutral_when_no_ai_mentioned() -> None:
    out = _compute(description="A simple task tracker for small teams.")
    assert out.architect_name == "AISkepticismArchitect"
    assert len(out.metrics) == 7
    assert out.metrics["ai_presence_score"] == 0.0
    assert out.metrics["ai_risk_load"] == 0.0
    assert out.metrics["ai_skepticism"] == 0.0
    assert out.metrics["ai_mitigation_credibility"] == 1.0
    assert out.metrics["perceived_ai_risk"] == 0.0
    assert out.metrics["ai_trust_gap"] == 0.0
    assert out.metrics["ai_funnel_suppressor"] == 1.0
    assert out.flags["ai_powered_offer"] is False
    assert out.flags["ai_trust_gap_active"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_null_and_blank_evidence_is_not_ai_presence() -> None:
    out = _compute(
        env_params={
            "product_type": "saas",
            "description": None,
        },
        assumptions=[None, {"text": None}, {"text": ""}, {"text": "   "}],
    )
    assert out.metrics["ai_presence_score"] == 0.0
    assert out.metrics["ai_funnel_suppressor"] == 1.0
    assert out.flags["ai_powered_offer"] is False
    assert out.severity == "INFO"


def test_duplicate_pitch_texts_are_counted_once() -> None:
    from app.simulation.architects.ai_skepticism import _collect_texts

    assert _collect_texts(
        [{"text": _RISKY_PITCH}],
        {"description": _RISKY_PITCH},
    ) == [_RISKY_PITCH.lower()]

    once = _compute(description=_RISKY_PITCH)
    twice = _compute(
        assumptions=[{"text": _RISKY_PITCH}],
        description=_RISKY_PITCH,
    )
    assert twice.metrics["ai_trust_gap"] == once.metrics["ai_trust_gap"]
    assert (
        twice.metrics["ai_funnel_suppressor"]
        == once.metrics["ai_funnel_suppressor"]
    )


# ---------------------------------------------------------------------------
# AI-presence extraction
# ---------------------------------------------------------------------------


def test_ai_free_and_negated_ai_are_not_presence() -> None:
    for description in (
        "We are AI-free and never collect data.",
        "This is not an AI product; plain rules engine.",
        "No chatbot, no automation - just humans.",
    ):
        out = _compute(description=description)
        assert out.metrics["ai_presence_score"] == 0.0, description
        assert out.flags["ai_powered_offer"] is False, description
        assert out.metrics["ai_funnel_suppressor"] == 1.0, description


def test_trailing_denial_of_ai_is_not_presence() -> None:
    for description in (
        "AI is not used in our product; it is a plain rules engine.",
        "AI is not part of the product; humans handle everything.",
        "AI will not be involved in processing.",
        "AI does not feature in our workflow.",
    ):
        out = _compute(description=description)
        assert out.metrics["ai_presence_score"] == 0.0, description
        assert out.flags["ai_powered_offer"] is False, description
        assert out.metrics["ai_funnel_suppressor"] == 1.0, description
        assert out.severity == "INFO", description


def test_not_just_ai_still_counts_as_presence() -> None:
    out = _compute(
        description="It is not just an AI assistant; humans verify results."
    )
    assert out.flags["ai_powered_offer"] is True
    assert out.metrics["ai_presence_score"] > 0.0


def test_trailing_focus_construction_still_counts_as_presence() -> None:
    out = _compute(
        description="AI is not just an assistant; humans verify every output."
    )
    assert out.flags["ai_powered_offer"] is True
    assert out.metrics["ai_presence_score"] > 0.0


def test_contrastive_ai_not_humans_still_counts_as_presence() -> None:
    out = _compute(description="AI, not humans, handles the review.")
    assert out.flags["ai_powered_offer"] is True
    assert out.metrics["ai_presence_score"] > 0.0


def test_no_human_review_is_risk_not_mitigation() -> None:
    out = _compute(
        description="The AI writes drafts but there is no human review."
    )
    assert out.flags["ai_powered_offer"] is True
    assert out.flags["automation_opacity_risk"] is True
    assert out.flags["human_fallback_present"] is False
    assert out.flags["ai_trust_gap_active"] is True
    assert out.severity == "WARNING"


def test_camera_free_device_is_not_a_data_risk() -> None:
    out = _compute(
        description=(
            "Our AI-powered camera-free device records no audio and "
            "keeps everything on-device."
        )
    )
    assert out.flags["ai_powered_offer"] is True
    assert out.flags["data_misuse_concern"] is False
    assert out.flags["data_control_mitigation_present"] is True


def test_third_party_audit_is_not_a_data_misuse_concern() -> None:
    for description in (
        "Our AI assistant is independently audited by a third party every "
        "quarter and explains its reasoning.",
        "Our AI model undergoes a third-party audit each release.",
    ):
        out = _compute(description=description)
        assert out.flags["ai_powered_offer"] is True, description
        assert out.flags["data_misuse_concern"] is False, description
        assert out.flags["ai_transparency_present"] is True, description


def test_risk_groups_are_flagged() -> None:
    out = _compute(
        description=(
            "The AI agent is fully automated with no human oversight, "
            "sometimes hallucinates answers, trains on your data, and "
            "replaces employees with no human touch."
        )
    )
    assert out.flags["automation_opacity_risk"] is True
    assert out.flags["hallucination_risk"] is True
    assert out.flags["data_misuse_concern"] is True
    assert out.flags["displacement_anxiety_risk"] is True
    assert out.flags["ai_trust_gap_active"] is True
    assert out.severity == "CRITICAL"


# ---------------------------------------------------------------------------
# Mitigation behaviour
# ---------------------------------------------------------------------------


def test_mitigations_cover_all_three_classes() -> None:
    out = _compute(description=_MITIGATED_PITCH)
    assert out.metrics["ai_mitigation_credibility"] == 0.9
    assert out.flags["human_fallback_present"] is True
    assert out.flags["ai_transparency_present"] is True
    assert out.flags["data_control_mitigation_present"] is True
    assert out.flags["ai_trust_gap_active"] is False
    assert out.metrics["ai_funnel_suppressor"] == 1.0
    assert out.severity == "INFO"


def test_hyphenated_human_review_counts_as_mitigation() -> None:
    out = _compute(
        description=(
            "Our AI assistant returns human-reviewed answers and keeps "
            "processing on-device."
        )
    )
    assert out.flags["human_fallback_present"] is True


def test_mitigations_reduce_but_do_not_erase_risk_when_partial() -> None:
    risky = _compute(description=_RISKY_PITCH)
    partial = _compute(
        description=(
            "Our AI chatbot is fully automated with no human oversight, "
            "trains on your data, but is fact-checked."
        )
    )
    assert partial.metrics["ai_mitigation_credibility"] == 0.3
    assert 0.0 < partial.metrics["ai_trust_gap"] < risky.metrics["ai_trust_gap"]
    assert partial.flags["ai_trust_gap_active"] is True


# ---------------------------------------------------------------------------
# Trait / demographic / product sensitivity
# ---------------------------------------------------------------------------


def test_skepticism_scales_with_cluster_traits() -> None:
    high = _compute(
        trust=0.2,
        risk_aversion=0.8,
        digital_literacy=0.2,
        patience_score=0.2,
        description=_RISKY_PITCH,
    )
    low = _compute(
        trust=0.8,
        risk_aversion=0.2,
        digital_literacy=0.8,
        patience_score=0.8,
        description=_RISKY_PITCH,
    )
    assert high.metrics["ai_skepticism"] > low.metrics["ai_skepticism"]
    assert high.metrics["ai_trust_gap"] > low.metrics["ai_trust_gap"]


def test_older_clusters_are_more_skeptical() -> None:
    senior = _compute(
        age_bracket="60-75",
        description="Our AI copilot writes your emails.",
    )
    young = _compute(
        age_bracket="17-22",
        description="Our AI copilot writes your emails.",
    )
    assert (
        senior.metrics["ai_skepticism"]
        > young.metrics["ai_skepticism"]
    )


def test_high_stake_product_types_raise_skepticism() -> None:
    health = _compute(
        product_type="health_hardware",
        description="Our AI health monitor tracks your vitals.",
    )
    saas = _compute(
        product_type="saas",
        description="Our AI health monitor tracks your vitals.",
    )
    assert health.metrics["ai_skepticism"] > saas.metrics["ai_skepticism"]


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_override_only_when_suppressed() -> None:
    neutral = _compute(description="Plain task tracker.")
    risky = _compute(description=_RISKY_PITCH)
    assert _architect().transition_overrides(neutral) == {}
    overrides = _architect().transition_overrides(risky)
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("DECIDE", "PURCHASE")] == risky.metrics[
        "ai_funnel_suppressor"
    ]
    assert 0.55 <= overrides[("DECIDE", "PURCHASE")] <= 0.999


# ---------------------------------------------------------------------------
# Cross-cluster report
# ---------------------------------------------------------------------------


def test_generate_report_handles_empty_outputs() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "AISkepticismArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"


def test_generate_report_aggregates_active_and_critical_clusters() -> None:
    active = _compute(
        trust=0.2,
        cluster_id="active_cluster",
        description=_RISKY_PITCH,
    )
    critical = _compute(
        trust=0.1,
        risk_aversion=0.9,
        digital_literacy=0.1,
        cluster_id="critical_cluster",
        description=_RISKY_PITCH,
    )
    report = _architect().generate_report([active, critical])
    assert report.architect_name == "AISkepticismArchitect"
    assert set(report.affected_cluster_ids) == {
        active.cluster_id,
        critical.cluster_id,
    }
    assert 0.0 < report.population_fraction <= 1.0
    assert report.conversion_impact > 0.0
    assert report.severity == "CRITICAL"
    assert "human fallback" in report.recommended_action.lower()


# ---------------------------------------------------------------------------
# Conductor + calibration + accountability integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": _RISKY_PITCH,
            "average_order_value": 999,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )
    assert "AISkepticismArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "AISkepticismArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "AISkepticismArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_every_product_stack() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
    )

    registry = build_architect_registry()
    assert "AISkepticismArchitect" in registry
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert "AISkepticismArchitect" in stack
        assert stack[0] == "MarketTimingArchitect"
        assert stack[-1] == "AssumptionCascadeArchitect"
        assert stack[-2] == "FounderExecutionArchitect"
        assert stack[-3] == "AISkepticismArchitect"


def test_registered_in_calibration_and_specificity_rules() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.scored_assumption import (
        SPECIFICITY_RULES,
        _score_specificity,
    )

    assert "AISkepticismArchitect" in ALL_ARCHITECT_NAMES
    assert "AISkepticismArchitect" in SPECIFICITY_RULES
    assert _score_specificity(
        "AISkepticismArchitect",
        "Our AI assistant is 99% accurate and audited quarterly",
    ) == 1.0
    assert _score_specificity("AISkepticismArchitect", "AI chatbot") == 0.6
    assert _score_specificity(
        "AISkepticismArchitect", "plain task tracker, no AI"
    ) == 0.0


def test_specificity_scores_verb_gapped_ai_denials_as_zero() -> None:
    from app.simulation.scored_assumption import _score_specificity

    for claim in (
        "Our product does not use AI at all",
        "AI is not used in our product",
        "AI will not be part of the product",
        "We avoid AI; human agents only",
        "No chatbot, no automation, no machine learning",
    ):
        assert _score_specificity("AISkepticismArchitect", claim) == 0.0, claim


def test_specificity_keeps_focus_and_risk_denials_as_claims() -> None:
    from app.simulation.scored_assumption import _score_specificity

    assert _score_specificity(
        "AISkepticismArchitect",
        "AI is not just an assistant; it is audited quarterly",
    ) == 1.0
    assert _score_specificity(
        "AISkepticismArchitect",
        "Our tool does not have AI limitations",
    ) == 0.6


def test_accountability_benchmarks_cover_ai_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "ai_risk_load",
        "ai_skepticism",
        "ai_mitigation_credibility",
        "perceived_ai_risk",
        "ai_trust_gap",
        "ai_funnel_suppressor",
    ):
        assert metric in benchmarks, metric
        assert metric in AccountabilityEngine.FINDING_TEMPLATES, metric
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS, metric
    assert "perceived_ai_risk" in AccountabilityEngine.LOWER_IS_BETTER
    assert "ai_trust_gap" in AccountabilityEngine.LOWER_IS_BETTER

"""
Tests for ``app.simulation.architects.integration_friction`` —
IntegrationFrictionArchitect.

Locks down existing-toolchain compatibility evidence extraction (API/SDK,
native integrations, import/export, SSO, workflow compatibility —
negation- and intent-aware), per-cluster friction modelling, Markov
overrides at CONSIDER→DECIDE, the cross-cluster report, and conductor /
calibration / specificity / accountability registration so the domain
surfaces as a founder finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    risk_aversion: float = 0.5,
    digital_literacy: float = 0.5,
    patience_score: float = 0.5,
    cluster_id: str = "test_cluster",
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    traits = {
        "income_level": 0.5,
        "digital_literacy": digital_literacy,
        "motivation": 0.5,
        "trust": 0.5,
        "price_sensitivity": 0.5,
        "risk_aversion": risk_aversion,
        "patience_score": patience_score,
        "social_orientation": 0.5,
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
    digital_literacy: float = 0.5,
    patience_score: float = 0.5,
    cluster_id: str = "test_cluster",
    assumptions: list[Any] | None = None,
    description: str = "",
    product_type: str = "saas",
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.integration_friction import (
        IntegrationFrictionArchitect,
    )

    if env_params is not None:
        params = dict(env_params)
        params.setdefault("product_type", product_type)
    else:
        params: dict[str, Any] = {"product_type": product_type}
        if description:
            params["description"] = description
    return IntegrationFrictionArchitect().compute(
        cluster=_cluster(
            risk_aversion=risk_aversion,
            digital_literacy=digital_literacy,
            patience_score=patience_score,
            cluster_id=cluster_id,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.integration_friction import (
        IntegrationFrictionArchitect,
    )

    return IntegrationFrictionArchitect()


def _output(
    *,
    cluster_id: str,
    friction: float,
    evidence: float,
    flags: dict[str, bool],
    severity: str = "WARNING",
) -> Any:
    from app.simulation.architects.base import ArchitectOutput

    return ArchitectOutput(
        architect_name="IntegrationFrictionArchitect",
        cluster_id=cluster_id,
        metrics={
            "integration_evidence_score": evidence,
            "integration_gap_score": 0.0,
            "integration_necessity": 0.7,
            "workflow_fit_score": 1.0 - friction,
            "integration_friction": friction,
            "integration_funnel_suppressor": 0.7 if friction >= 0.35 else 1.0,
        },
        flags=flags,
        narrative_findings=[],
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types_are_software_categories() -> None:
    architect = _architect()
    assert architect.name == "IntegrationFrictionArchitect"
    assert set(architect.product_types) == {
        "saas", "marketplace", "developer_tool", "enterprise_software",
        "b2b_marketplace", "productivity_tool", "mobile_app", "consumer_app",
    }


def test_baseline_compute_is_neutral_when_pitch_never_mentions_integration() -> None:
    out = _compute(description="A simple task tracker for small teams.")
    assert out.architect_name == "IntegrationFrictionArchitect"
    assert out.metrics["integration_evidence_score"] == 1.0
    assert out.metrics["integration_gap_score"] == 0.0
    assert out.metrics["integration_friction"] == 0.0
    assert out.metrics["integration_funnel_suppressor"] == 1.0
    assert out.flags["integration_topic_discussed"] is False
    assert out.flags["integration_gap_detected"] is False
    assert out.flags["integration_friction_active"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_null_and_blank_evidence_is_neutral() -> None:
    out = _compute(
        env_params={"product_type": "saas", "description": None},
        assumptions=[None, {"text": None}, {"text": ""}, {"text": "   "}],
    )
    assert out.metrics["integration_friction"] == 0.0
    assert out.metrics["integration_funnel_suppressor"] == 1.0
    assert out.flags["integration_topic_discussed"] is False
    assert out.severity == "INFO"


def test_duplicate_pitch_texts_are_counted_once() -> None:
    from app.simulation.architects.integration_friction import _collect_texts

    pitch = "REST API, Slack integration and CSV import are available."
    assert _collect_texts(
        [{"text": pitch}],
        {"description": pitch},
    ) == [pitch.lower()]

    once = _compute(description=pitch)
    twice = _compute(assumptions=[{"text": pitch}], description=pitch)
    assert twice.metrics == once.metrics


# ---------------------------------------------------------------------------
# Evidence extraction (negation- and intent-aware)
# ---------------------------------------------------------------------------


def test_evidence_score_covers_five_classes() -> None:
    out = _compute(
        description=(
            "REST API, SDK and webhooks; Slack and Salesforce integrations; "
            "CSV import/export with migration tools; SSO with Okta and "
            "SCIM; works with Google Workspace and Excel."
        )
    )
    assert out.metrics["integration_evidence_score"] == 1.0
    assert out.flags["integration_topic_discussed"] is True
    assert out.flags["integration_evidence_strong"] is True
    assert out.flags["api_evidence_present"] is True
    assert out.flags["native_integration_evidence_present"] is True
    assert out.flags["import_export_evidence_present"] is True
    assert out.flags["sso_evidence_present"] is True
    assert out.flags["workflow_compat_evidence_present"] is True
    assert out.metrics["integration_friction"] < 0.35
    assert out.metrics["integration_funnel_suppressor"] == 1.0
    assert out.severity == "INFO"


def test_two_evidence_classes_score_half() -> None:
    out = _compute(description="We expose a REST API and a Python SDK.")
    assert out.metrics["integration_evidence_score"] == 0.3
    assert out.flags["integration_evidence_strong"] is False


def test_negated_integration_claims_are_gaps_not_evidence() -> None:
    out = _compute(
        risk_aversion=0.9,
        digital_literacy=0.2,
        patience_score=0.2,
        description=(
            "No API, no SDK, no integrations, no SSO and no export; "
            "data is locked in a closed system."
        ),
    )
    assert out.metrics["integration_evidence_score"] == 0.0
    assert out.metrics["integration_gap_score"] == 1.0
    assert out.flags["integration_gap_detected"] is True
    assert out.flags["integration_friction_active"] is True
    assert out.metrics["integration_funnel_suppressor"] < 1.0
    assert out.severity == "CRITICAL"


def test_no_api_key_required_is_not_a_gap() -> None:
    out = _compute(
        description="No API key required - the app works with Excel.",
    )
    assert out.metrics["integration_gap_score"] == 0.0
    assert out.flags["integration_gap_detected"] is False
    assert out.flags["native_integration_evidence_present"] is True
    assert out.flags["workflow_compat_evidence_present"] is True


def test_discourse_negation_keeps_evidence_positive() -> None:
    out = _compute(
        description=(
            "No, we already have a REST API and a Salesforce integration."
        )
    )
    assert out.metrics["integration_gap_score"] == 0.0
    assert out.flags["api_evidence_present"] is True
    assert out.flags["native_integration_evidence_present"] is True
    assert out.metrics["integration_evidence_score"] == 0.6


def test_intent_only_claims_are_not_evidence_and_not_gaps() -> None:
    out = _compute(
        description=(
            "We plan to add an API and will build a Zapier integration."
        )
    )
    assert out.flags["integration_topic_discussed"] is False
    assert out.metrics["integration_gap_score"] == 0.0
    assert out.metrics["integration_evidence_score"] == 1.0
    assert _architect().transition_overrides(out) == {}


def test_negated_integration_verb_is_a_gap() -> None:
    out = _compute(
        risk_aversion=0.8,
        digital_literacy=0.2,
        patience_score=0.2,
        description="Our product does not integrate with Slack.",
    )
    assert out.metrics["integration_gap_score"] >= 0.3
    assert out.flags["integration_gap_detected"] is True
    assert out.flags["integration_friction_active"] is True
    assert out.flags["native_integration_evidence_present"] is False


def test_question_clauses_are_not_evidence() -> None:
    out = _compute(
        description="Do you have an API? How do I export my data?",
    )
    assert out.flags["integration_topic_discussed"] is False
    assert out.metrics["integration_gap_score"] == 0.0
    assert out.metrics["integration_evidence_score"] == 1.0


# ---------------------------------------------------------------------------
# Trait- and category-driven sensitivity
# ---------------------------------------------------------------------------


def test_low_literacy_impatient_clusters_suffer_more_friction() -> None:
    gap_text = "No API, manual data entry into our closed system."
    cautious = _compute(
        risk_aversion=0.9,
        digital_literacy=0.1,
        patience_score=0.1,
        description=gap_text,
    )
    confident = _compute(
        risk_aversion=0.2,
        digital_literacy=0.9,
        patience_score=0.9,
        description=gap_text,
    )
    assert cautious.metrics["integration_necessity"] > confident.metrics["integration_necessity"]
    assert cautious.metrics["integration_friction"] > confident.metrics["integration_friction"]
    assert (
        cautious.metrics["integration_funnel_suppressor"]
        < confident.metrics["integration_funnel_suppressor"]
    )


def test_enterprise_and_developer_tools_have_higher_necessity() -> None:
    gap_text = "No API and no SSO."
    enterprise = _compute(product_type="enterprise_software", description=gap_text)
    consumer = _compute(product_type="consumer_app", description=gap_text)
    assert (
        enterprise.metrics["integration_necessity"]
        > consumer.metrics["integration_necessity"]
    )
    assert enterprise.metrics["integration_friction"] > consumer.metrics["integration_friction"]


def test_strong_evidence_earns_a_small_workflow_fit_lift() -> None:
    out = _compute(
        product_type="enterprise_software",
        description=(
            "REST API, Slack and Salesforce integrations, CSV import, "
            "SSO with Okta, and it works with Google Sheets."
        ),
    )
    assert out.flags["integration_fit_lift_active"] is True
    overrides = _architect().transition_overrides(out)
    assert ("CONSIDER", "DECIDE") in overrides
    assert overrides[("CONSIDER", "DECIDE")] > 1.0


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_suppress_when_friction_is_active() -> None:
    out = _compute(
        risk_aversion=0.9,
        digital_literacy=0.1,
        patience_score=0.1,
        description="No API, no integrations, manual data entry.",
    )
    overrides = _architect().transition_overrides(out)
    assert ("CONSIDER", "DECIDE") in overrides
    assert overrides[("CONSIDER", "DECIDE")] < 1.0
    assert ("DECIDE", "PURCHASE") not in overrides
    assert ("BROWSE", "CONSIDER") not in overrides


def test_transition_overrides_are_empty_when_not_discussed() -> None:
    out = _compute(description="A simple task tracker for small teams.")
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Cross-cluster report
# ---------------------------------------------------------------------------


def test_generate_report_handles_empty_outputs() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "IntegrationFrictionArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"


def test_generate_report_names_top_missing_evidence_class() -> None:
    affected = _output(
        cluster_id="risk_averse_saver",
        friction=0.7,
        evidence=0.0,
        flags={
            "integration_topic_discussed": True,
            "integration_friction_active": True,
            "api_evidence_present": True,
            "native_integration_evidence_present": False,
            "import_export_evidence_present": True,
            "sso_evidence_present": False,
            "workflow_compat_evidence_present": False,
        },
        severity="CRITICAL",
    )
    calm = _output(
        cluster_id="metro_power_professional",
        friction=0.1,
        evidence=1.0,
        flags={
            "integration_topic_discussed": True,
            "integration_friction_active": False,
            "api_evidence_present": True,
            "native_integration_evidence_present": True,
            "import_export_evidence_present": True,
            "sso_evidence_present": True,
            "workflow_compat_evidence_present": True,
        },
        severity="INFO",
    )
    report = _architect().generate_report([affected, calm])
    assert report.affected_cluster_ids == ["risk_averse_saver"]
    assert "native integrations" in report.primary_finding
    assert "Slack, Salesforce, Zapier" in report.recommended_action
    assert report.severity == "WARNING"
    assert report.population_fraction > 0.0


def test_generate_report_is_critical_when_many_clusters_are_critical() -> None:
    outputs = [
        _output(
            cluster_id=f"cluster_{i}",
            friction=0.8,
            evidence=0.0,
            flags={
                "integration_topic_discussed": True,
                "integration_friction_active": True,
                "api_evidence_present": False,
                "native_integration_evidence_present": False,
                "import_export_evidence_present": False,
                "sso_evidence_present": False,
                "workflow_compat_evidence_present": False,
            },
            severity="CRITICAL",
        )
        for i in range(4)
    ]
    report = _architect().generate_report(outputs)
    assert report.severity == "CRITICAL"
    assert len(report.affected_cluster_ids) == 4
    assert report.recommended_action.startswith("Publish API/SDK/webhook")


def test_generate_report_is_neutral_without_active_friction() -> None:
    calm = _output(
        cluster_id="metro_power_professional",
        friction=0.1,
        evidence=1.0,
        flags={
            "integration_topic_discussed": True,
            "integration_friction_active": False,
            "api_evidence_present": True,
            "native_integration_evidence_present": True,
            "import_export_evidence_present": True,
            "sso_evidence_present": True,
            "workflow_compat_evidence_present": True,
        },
        severity="INFO",
    )
    report = _architect().generate_report([calm])
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert "No dominant integration blocker" in report.recommended_action


# ---------------------------------------------------------------------------
# Conductor + calibration + accountability integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "A SaaS CRM for small businesses",
            "average_order_value": 999,
        },
        assumptions=[
            {
                "text": (
                    "We have no API, no integrations, and users must "
                    "enter data manually"
                )
            }
        ],
        product_type=ProductType.SAAS,
    )
    assert "IntegrationFrictionArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "IntegrationFrictionArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "IntegrationFrictionArchitect"
        for finding in findings
    )


def test_conductor_neutral_pitch_stays_quiet_in_accountability() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "A simple task tracker for small teams",
            "average_order_value": 999,
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert not any(
        finding.architect_name == "IntegrationFrictionArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_software_stacks_only() -> None:
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
        _build_architect_registry,
    )

    registry = _build_architect_registry()
    assert "IntegrationFrictionArchitect" in registry
    software = {
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
        ProductType.ENTERPRISE_SOFTWARE,
        ProductType.CONSUMER_APP,
        ProductType.B2B_MARKETPLACE,
        ProductType.PRODUCTIVITY_TOOL,
    }
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert stack[0] == "MarketTimingArchitect"
        assert stack[-1] == "AssumptionCascadeArchitect"
        if product_type in software:
            assert "IntegrationFrictionArchitect" in stack
        else:
            assert "IntegrationFrictionArchitect" not in stack


def test_registered_in_calibration_and_specificity_rules() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES
    from app.simulation.scored_assumption import (
        SPECIFICITY_RULES,
        _score_specificity,
    )

    assert "IntegrationFrictionArchitect" in ALL_ARCHITECT_NAMES
    assert "IntegrationFrictionArchitect" in SPECIFICITY_RULES
    assert _score_specificity(
        "IntegrationFrictionArchitect",
        "REST API, SDK, webhooks, Salesforce and CSV import with SSO",
    ) == 1.0
    assert _score_specificity(
        "IntegrationFrictionArchitect",
        "We offer an API with integrations",
    ) == 0.6
    assert _score_specificity(
        "IntegrationFrictionArchitect",
        "Connects seamlessly with your stack",
    ) == 0.2
    assert _score_specificity(
        "IntegrationFrictionArchitect",
        "A plain task tracker for small teams",
    ) == 0.0


def test_specificity_scores_integration_denials_as_zero() -> None:
    from app.simulation.scored_assumption import _score_specificity

    for claim in (
        "No API, no SDK and no integrations",
        "Our product does not integrate with Slack",
        "We do not offer SSO or export",
        "Cannot connect to your CRM",
    ):
        assert _score_specificity("IntegrationFrictionArchitect", claim) == 0.0, claim


def test_specificity_keeps_no_api_key_claim_as_mechanism() -> None:
    from app.simulation.scored_assumption import _score_specificity

    assert _score_specificity(
        "IntegrationFrictionArchitect",
        "No API key required",
    ) == 0.6


def test_accountability_benchmarks_cover_integration_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "integration_evidence_score",
        "integration_gap_score",
        "workflow_fit_score",
        "integration_friction",
        "integration_funnel_suppressor",
    ):
        assert metric in benchmarks, metric
        assert metric in AccountabilityEngine.FINDING_TEMPLATES, metric
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS, metric
    assert "integration_gap_score" in AccountabilityEngine.LOWER_IS_BETTER
    assert "integration_friction" in AccountabilityEngine.LOWER_IS_BETTER
    assert "integration_evidence_score" not in AccountabilityEngine.LOWER_IS_BETTER
    assert "workflow_fit_score" not in AccountabilityEngine.LOWER_IS_BETTER
    assert "integration_funnel_suppressor" not in AccountabilityEngine.LOWER_IS_BETTER

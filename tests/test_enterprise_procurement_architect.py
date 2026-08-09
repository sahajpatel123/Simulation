"""
Tests for ``app.simulation.architects.enterprise_procurement`` —
EnterpriseProcurementArchitect.

Locks down B2B procurement-signal detection, security-review and
vendor-panel barrier modelling, negation- and intent-aware evidence
handling, PoC/pilot and sales-assistance requirements, severity tiers,
flags, narrative findings, Markov transition overrides, and the
cross-cluster generate_report() rollup — plus conductor, accountability
and calibration registration so the domain surfaces as a founder finding.
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
    cluster_id: str = "enterprise_procurement_gatekeeper",
    affinities: list[str] | None = None,
) -> Any:
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.03,
        base_traits={
            "income_level": income,
            "digital_literacy": literacy,
            "motivation": 0.5,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": 0.5,
            "social_orientation": 0.5,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=affinities or ["enterprise_software", "saas"],
        demographic_profile={"geography": "metro", "age_bracket": "38-55"},
    )


def _compute(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    cluster_id: str = "enterprise_procurement_gatekeeper",
    affinities: list[str] | None = None,
    assumptions: list[Any] | None = None,
    agent_profile: dict[str, Any] | None = None,
    product_type: str = "enterprise_software",
) -> Any:
    from app.simulation.architects.enterprise_procurement import (
        EnterpriseProcurementArchitect,
    )

    return EnterpriseProcurementArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            income=income,
            price_sens=price_sens,
            cluster_id=cluster_id,
            affinities=affinities,
        ),
        agent_profile=agent_profile or {},
        assumptions=assumptions or [],
        env_params={"product_type": product_type},
    )


def _architect() -> Any:
    from app.simulation.architects.enterprise_procurement import (
        EnterpriseProcurementArchitect,
    )

    return EnterpriseProcurementArchitect()


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "EnterpriseProcurementArchitect"
    assert set(architect.product_types) == {
        "saas", "developer_tool", "enterprise_software",
        "b2b_hardware", "b2b_marketplace", "productivity_tool",
    }


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute(
        cluster_id="low_literacy_student_passive",
        affinities=[],
        product_type="saas",
    )
    assert out.architect_name == "EnterpriseProcurementArchitect"
    assert len(out.metrics) == 12
    assert out.metrics["procurement_exposure"] < 0.15
    assert out.metrics["procurement_friction"] == 0.0
    assert out.metrics["procurement_credibility"] == 1.0
    assert out.metrics["funnel_suppressor"] == 1.0
    assert out.metrics["procurement_advantage_lift"] == 0.0
    assert all(
        0.0 <= value <= 1.0
        for key, value in out.metrics.items()
        if key != "procurement_cycle_days"
    )
    assert out.metrics["procurement_cycle_days"] == 0.0
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    out = _compute(
        cluster_id="low_literacy_student_passive",
        affinities=[],
        product_type="saas",
    )
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Exposure and friction modelling
# ---------------------------------------------------------------------------


def test_enterprise_assumption_raises_exposure_and_friction() -> None:
    out = _compute(
        risk=0.8,
        trust=0.35,
        assumptions=[
            {
                "text": "We require security review and "
                "procurement approval before purchase"
            }
        ],
    )
    assert out.metrics["procurement_exposure"] > 0.15
    assert out.metrics["security_review_barrier"] > 0.35
    assert out.metrics["vendor_list_barrier"] > 0.35
    assert out.metrics["procurement_friction"] >= 0.40
    assert out.flags["security_review_blocker"] is True
    assert out.flags["vendor_panel_blocked"] is True
    assert out.flags["procurement_gate_critical"] is True
    assert out.severity == "CRITICAL"

    overrides = _architect().transition_overrides(out)
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("CONSIDER", "DECIDE")] < 1.0
    assert overrides[("DECIDE", "PURCHASE")] < 1.0


def test_evidence_clears_blockers_and_adds_purchase_lift() -> None:
    out = _compute(
        risk=0.8,
        trust=0.35,
        assumptions=[
            {
                "text": "We require security review and "
                "procurement approval before purchase"
            },
            {
                "text": "SOC 2 report available and signed MSA and DPA"
            },
        ],
    )
    assert out.metrics["procurement_credibility"] == 1.0
    assert out.metrics["procurement_advantage_lift"] > 0.0
    assert out.flags["security_review_blocker"] is False
    assert out.flags["vendor_panel_blocked"] is False
    assert out.flags["procurement_advantage"] is True

    overrides = _architect().transition_overrides(out)
    assert overrides[("DECIDE", "PURCHASE")] > 1.0


def test_poc_signal_raises_poc_requirement() -> None:
    out = _compute(
        risk=0.7,
        assumptions=[
            {"text": "Enterprise buyers require a 30-day pilot before signing"}
        ],
    )
    assert out.metrics["poc_requirement"] >= 0.5
    assert out.flags["poc_required"] is True
    assert out.severity in ("WARNING", "CRITICAL")


def test_sales_led_motion_raises_sales_assistance() -> None:
    out = _compute(
        assumptions=[
            {"text": "Sales-led motion with account executives for enterprise"}
        ],
    )
    assert out.metrics["sales_assistance_requirement"] >= 0.5
    assert out.flags["sales_assistance_required"] is True


def test_self_serve_lowers_sales_assistance_and_cycle() -> None:
    out = _compute(
        assumptions=[
            {"text": "Self-serve signup with free trial"}
        ],
    )
    assert out.metrics["sales_assistance_requirement"] <= 0.2
    assert out.flags["sales_assistance_required"] is False
    assert out.metrics["procurement_cycle_days"] <= 60.0


# ---------------------------------------------------------------------------
# Negation- and intent-aware evidence handling
# ---------------------------------------------------------------------------


def test_negative_procurement_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {
                "text": "We do not have SOC 2 and vendor approval is missing"
            }
        ],
    )
    assert out.metrics["procurement_credibility"] < 1.0
    assert out.flags["security_review_blocker"] is True
    assert out.flags["vendor_panel_blocked"] is True


def test_intent_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {
                "text": "We plan to obtain SOC 2 and get on the vendor panel"
            }
        ],
    )
    assert out.metrics["procurement_credibility"] < 1.0
    assert out.flags["security_review_blocker"] is True


def test_discourse_negation_keeps_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We do not have SOC 2 yet"},
            {"text": "No, we already have SOC 2 and ISO 27001"},
        ],
    )
    assert out.metrics["procurement_credibility"] == 1.0
    assert out.flags["security_review_blocker"] is False
    assert out.flags["procurement_advantage"] is True


def test_plain_evidence_mention_is_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We have SOC 2 and ISO 27001"},
        ],
    )
    assert out.metrics["procurement_credibility"] == 1.0
    assert out.flags["procurement_advantage"] is True


def test_phrase_intent_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We are working on SOC 2 certification"},
        ],
    )
    assert out.metrics["procurement_credibility"] < 1.0
    assert out.flags["security_review_blocker"] is True


def test_sibling_intent_does_not_void_existing_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We have SOC 2 and are working on ISO 27001"},
        ],
    )
    assert out.metrics["procurement_credibility"] == 1.0
    assert out.flags["security_review_blocker"] is False


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "EnterpriseProcurementArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0
    assert report.conversion_impact == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="enterprise_procurement_gatekeeper",
        metrics={},
        flags={"procurement_gate_critical": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="mid_market_it_decision_maker",
        metrics={},
        flags={"security_review_blocker": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {
        "enterprise_procurement_gatekeeper",
        "mid_market_it_decision_maker",
    }
    assert report.conversion_impact > 0.0


# ---------------------------------------------------------------------------
# Conductor + accountability integration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "Enterprise compliance platform",
            "average_order_value": 999,
            "market_maturity": 0.5,
        },
        assumptions=[
            {
                "text": "Requires security review and procurement "
                "approval before purchase"
            }
        ],
        product_type=ProductType.ENTERPRISE_SOFTWARE,
    )
    assert "EnterpriseProcurementArchitect" in result.cluster_results[
        "enterprise_procurement_gatekeeper"
    ]
    assert any(
        report.architect_name == "EnterpriseProcurementArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "EnterpriseProcurementArchitect"
        for finding in findings
    )


def test_registry_includes_new_architect_in_b2b_stacks() -> None:
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
        _build_architect_registry,
    )

    registry = _build_architect_registry()
    assert "EnterpriseProcurementArchitect" in registry
    for product_type in (
        ProductType.SAAS,
        ProductType.DEVELOPER_TOOL,
        ProductType.ENTERPRISE_SOFTWARE,
        ProductType.B2B_HARDWARE,
        ProductType.B2B_MARKETPLACE,
        ProductType.PRODUCTIVITY_TOOL,
    ):
        assert "EnterpriseProcurementArchitect" in ARCHITECT_STACKS[product_type]
        assert ARCHITECT_STACKS[product_type][-1] == "AssumptionCascadeArchitect"

    assert "EnterpriseProcurementArchitect" not in ARCHITECT_STACKS[
        ProductType.MOBILE_APP
    ]
    assert "EnterpriseProcurementArchitect" not in ARCHITECT_STACKS[
        ProductType.CONSUMER_APP
    ]


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "EnterpriseProcurementArchitect" in ALL_ARCHITECT_NAMES

"""
Tests for ``app.simulation.architects.regulatory_compliance`` —
RegulatoryComplianceArchitect.

Locks down exposure detection (privacy/financial/health/certification/
consumer protection), concern modelling, compliance-credibility handling,
severity tiers, flags, narrative findings, Markov transition overrides, and
the cross-cluster generate_report() rollup — plus end-to-end conductor
integration so the new domain actually surfaces as an accountability finding.
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
        product_affinities=["saas"],
        demographic_profile={"geography": "metro_delhi", "age_bracket": "25-35"},
    )


def _compute(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    assumptions: list[dict[str, str]] | None = None,
    product_type: str = "saas",
) -> Any:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    return RegulatoryComplianceArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            income=income,
            price_sens=price_sens,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params={"product_type": product_type},
    )


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    architect = RegulatoryComplianceArchitect()
    assert architect.name == "RegulatoryComplianceArchitect"
    # Empty list = active for every product type.
    assert architect.product_types == []


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "RegulatoryComplianceArchitect"
    assert len(out.metrics) == 8
    assert out.metrics["regulatory_exposure"] == 0.08
    assert out.metrics["regulatory_suppressor"] == 1.0
    assert out.metrics["regulatory_advantage_lift"] == 0.0
    assert abs(out.metrics["compliance_credibility"] - 0.928) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    architect = RegulatoryComplianceArchitect()
    out = _compute()
    assert architect.transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Privacy exposure
# ---------------------------------------------------------------------------


def test_privacy_assumption_raises_exposure_and_concern() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        assumptions=[{"text": "App collects personal data and location data"}],
    )
    assert out.metrics["regulatory_exposure"] > 0.15
    assert out.metrics["privacy_concern_intensity"] > 0.25
    assert out.metrics["consent_friction"] > 0.0
    assert out.severity == "WARNING"


def test_privacy_blocker_flag_on_distrustful_risk_averse_cluster() -> None:
    out = _compute(
        trust=0.15,
        risk=0.85,
        assumptions=[{"text": "Collects health data and location data"}],
    )
    assert out.flags["privacy_blocker"] is True
    assert out.flags["compliance_unknown"] is True


# ---------------------------------------------------------------------------
# Certification gate
# ---------------------------------------------------------------------------


def test_certification_gate_on_health_hardware_without_evidence() -> None:
    out = _compute(
        product_type="health_hardware",
        assumptions=[{"text": "Requires FDA approval before launch"}],
    )
    assert out.metrics["certification_barrier"] >= 0.60
    assert out.flags["certification_gate"] is True
    assert out.severity == "CRITICAL"


def test_compliance_evidence_clears_certification_gate_and_raises_credibility() -> None:
    out = _compute(
        product_type="health_hardware",
        assumptions=[
            {"text": "Requires FDA approval before launch"},
            {"text": "FDA approved and ISO 13485 certified"},
        ],
    )
    assert out.metrics["compliance_credibility"] == 1.0
    assert out.flags["certification_gate"] is False
    assert out.flags["regulatory_advantage"] is True
    assert out.metrics["regulatory_advantage_lift"] > 0.0


# ---------------------------------------------------------------------------
# Refund / liability concern
# ---------------------------------------------------------------------------


def test_refund_concern_for_price_sensitive_low_income_consumer() -> None:
    out = _compute(
        income=0.2,
        price_sens=0.9,
        product_type="d2c",
        assumptions=[{"text": "Liability risk if the device fails"}],
    )
    assert out.metrics["refund_liability_concern"] >= 0.35
    assert out.flags["refund_policy_risk"] is True


def test_refund_policy_mention_lowers_concern() -> None:
    out = _compute(
        income=0.2,
        price_sens=0.9,
        product_type="d2c",
        assumptions=[
            {"text": "Liability risk if the device fails"},
            {"text": "Clear refund and return policy"},
        ],
    )
    assert out.flags["refund_policy_risk"] is False
    assert out.metrics["refund_liability_concern"] < 0.35


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_active_only_with_exposure() -> None:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    architect = RegulatoryComplianceArchitect()
    neutral = _compute()
    assert architect.transition_overrides(neutral) == {}

    exposed = _compute(
        trust=0.3,
        risk=0.7,
        assumptions=[{"text": "RBI regulated payment product"}],
    )
    overrides = architect.transition_overrides(exposed)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert overrides[("BROWSE", "CONSIDER")] < 1.0


def test_evidence_softens_suppressor_and_adds_purchase_lift() -> None:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    architect = RegulatoryComplianceArchitect()
    bare = _compute(
        trust=0.3,
        risk=0.7,
        assumptions=[{"text": "RBI regulated payment product"}],
    )
    evidenced = _compute(
        trust=0.3,
        risk=0.7,
        assumptions=[
            {"text": "RBI regulated payment product"},
            {"text": "RBI approved and audited"},
        ],
    )
    bare_overrides = architect.transition_overrides(bare)
    evidenced_overrides = architect.transition_overrides(evidenced)
    assert (
        evidenced_overrides[("BROWSE", "CONSIDER")]
        > bare_overrides[("BROWSE", "CONSIDER")]
    )
    assert evidenced_overrides[("DECIDE", "PURCHASE")] > 1.0


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    report = RegulatoryComplianceArchitect().generate_report([])
    assert report.architect_name == "RegulatoryComplianceArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput
    from app.simulation.architects.regulatory_compliance import (
        RegulatoryComplianceArchitect,
    )

    architect = RegulatoryComplianceArchitect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="skeptic_cluster",
        metrics={},
        flags={"privacy_blocker": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="late_majority_cluster",
        metrics={},
        flags={"compliance_unknown": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {
        "skeptic_cluster",
        "late_majority_cluster",
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
            "description": "A privacy-first mobile app",
            "average_order_value": 499,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "Collects personal data and location data"}
        ],
        product_type=ProductType.MOBILE_APP,
    )
    assert "RegulatoryComplianceArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "RegulatoryComplianceArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "RegulatoryComplianceArchitect"
        for finding in findings
    )


def test_registry_includes_new_architect_in_every_stack() -> None:
    from app.simulation.conductor import ARCHITECT_STACKS, _build_architect_registry

    registry = _build_architect_registry()
    assert "RegulatoryComplianceArchitect" in registry
    for stack in ARCHITECT_STACKS.values():
        assert "RegulatoryComplianceArchitect" in stack
        assert stack[-1] == "AssumptionCascadeArchitect"

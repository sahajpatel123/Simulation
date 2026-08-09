"""
Tests for ``app.simulation.architects.payment_friction`` —
PaymentFrictionArchitect.

Locks down payment-exposure detection, payment-method coverage, checkout
friction, cash/financing dependency, negation- and intent-aware evidence
handling, severity tiers, flags, narrative findings, Markov transition
overrides, and the cross-cluster generate_report() rollup — plus conductor
and calibration registration so the new domain actually surfaces as an
accountability finding.
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
    geography: str = "metro_delhi",
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
        demographic_profile={
            "geography": geography,
            "age_bracket": "25-35",
        },
    )


def _compute(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    assumptions: list[Any] | None = None,
    product_type: str = "saas",
    aov: float = 999.0,
    geography: str = "metro_delhi",
) -> Any:
    from app.simulation.architects.payment_friction import (
        PaymentFrictionArchitect,
    )

    return PaymentFrictionArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            income=income,
            price_sens=price_sens,
            geography=geography,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params={
            "product_type": product_type,
            "average_order_value": aov,
        },
    )


def _architect() -> Any:
    from app.simulation.architects.payment_friction import (
        PaymentFrictionArchitect,
    )

    return PaymentFrictionArchitect()


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "PaymentFrictionArchitect"
    # Empty list = active for every product type.
    assert architect.product_types == []


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "PaymentFrictionArchitect"
    assert len(out.metrics) == 11
    assert out.metrics["payment_exposure"] == 0.08
    assert out.metrics["payment_method_coverage"] == 1.0
    assert out.metrics["funnel_suppressor"] == 1.0
    assert out.metrics["payment_advantage_lift"] == 0.0
    assert abs(out.metrics["payment_credibility"] - 0.932) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    out = _compute()
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Exposure and gap modelling
# ---------------------------------------------------------------------------


def test_payment_mention_without_evidence_raises_exposure_and_gap() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {
                "text": "We need to set up UPI and "
                "cash on delivery payments"
            }
        ],
    )
    assert out.metrics["payment_exposure"] == 0.26
    assert out.metrics["payment_method_coverage"] == 0.75
    assert out.metrics["payment_credibility"] < 1.0
    assert out.flags["payment_advantage"] is False
    assert out.flags["cash_dependency_gap"] is True
    assert out.severity == "CRITICAL"
    assert _architect().transition_overrides(out)


def test_restricted_checkout_blocks_low_trust_tier3_cluster() -> None:
    out = _compute(
        trust=0.15,
        risk=0.85,
        literacy=0.3,
        income=0.2,
        price_sens=0.8,
        geography="tier3_rural",
        assumptions=[
            {"text": "Checkout requires a credit card and no UPI"}
        ],
    )
    assert out.metrics["payment_exposure"] == 0.62
    assert out.metrics["payment_method_coverage"] == 0.4
    assert out.metrics["checkout_friction"] >= 0.4
    assert out.flags["checkout_blocker"] is True
    assert out.flags["payment_method_gap"] is True
    assert out.flags["payment_unknown"] is True
    assert out.severity == "CRITICAL"


def test_payment_evidence_clears_blocker_and_raises_credibility() -> None:
    out = _compute(
        trust=0.2,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        price_sens=0.8,
        geography="tier3_rural",
        assumptions=[
            {
                "text": "We accept UPI, debit cards, "
                "cash on delivery, and EMI"
            }
        ],
    )
    assert out.metrics["payment_method_coverage"] == 1.0
    assert out.metrics["payment_credibility"] == 1.0
    assert out.metrics["payment_advantage_lift"] > 0.0
    assert out.flags["payment_advantage"] is True
    assert out.flags["checkout_blocker"] is False
    assert out.flags["cash_dependency_gap"] is False
    assert out.flags["financing_gap"] is False
    assert out.severity == "INFO"


def test_financing_gap_on_high_aov_price_sensitive_buyer() -> None:
    out = _compute(
        trust=0.6,
        risk=0.7,
        literacy=0.7,
        income=0.6,
        price_sens=0.8,
        product_type="consumer_hardware",
        aov=15000,
        assumptions=[
            {"text": "We support UPI payments"}
        ],
    )
    assert out.metrics["financing_dependency"] >= 0.5
    assert out.flags["financing_gap"] is True
    assert out.severity == "WARNING"


def test_financing_evidence_clears_financing_gap() -> None:
    out = _compute(
        trust=0.6,
        risk=0.7,
        literacy=0.7,
        income=0.6,
        price_sens=0.8,
        product_type="consumer_hardware",
        aov=15000,
        assumptions=[
            {"text": "UPI payments supported and EMI options are available"}
        ],
    )
    assert out.metrics["financing_dependency"] < 0.5
    assert out.flags["financing_gap"] is False
    assert out.flags["payment_advantage"] is True


# ---------------------------------------------------------------------------
# Negation- and intent-aware evidence handling
# ---------------------------------------------------------------------------


def test_negative_payment_language_is_not_evidence() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We don't accept UPI yet and COD is unavailable"}
        ],
    )
    assert out.metrics["payment_credibility"] < 1.0
    assert out.flags["payment_advantage"] is False
    assert out.metrics["payment_advantage_lift"] == 0.0
    assert out.flags["cash_dependency_gap"] is True


def test_contracted_negation_is_not_evidence() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We don't support UPI and aren't offering COD"}
        ],
    )
    assert out.metrics["payment_credibility"] < 1.0
    assert out.metrics["payment_advantage_lift"] == 0.0
    assert out.flags["payment_advantage"] is False
    assert out.flags["cash_dependency_gap"] is True


def test_discourse_negation_does_not_void_evidence() -> None:
    out = _compute(
        trust=0.2,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[{"text": "No, we already accept UPI and COD"}],
    )
    assert out.metrics["payment_credibility"] == 1.0
    assert out.flags["payment_advantage"] is True
    assert out.metrics["payment_advantage_lift"] > 0.0
    assert out.flags["cash_dependency_gap"] is False


def test_intent_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We plan to add UPI and EMI later"}
        ],
    )
    assert out.metrics["payment_credibility"] < 1.0
    assert out.flags["payment_advantage"] is False
    assert out.metrics["payment_advantage_lift"] == 0.0


def test_completed_integration_is_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "We have integrated UPI"}
        ],
    )
    assert out.metrics["payment_credibility"] == 1.0
    assert out.flags["payment_advantage"] is True


def test_restricted_phrase_not_voided_by_discourse_negation() -> None:
    out = _compute(
        assumptions=[
            {"text": "Not only credit card but also UPI is accepted"}
        ],
    )
    assert out.metrics["payment_method_coverage"] == 1.0
    assert out.flags["payment_advantage"] is True


def test_negation_in_unrelated_clause_does_not_void_evidence() -> None:
    for text in (
        "We accept UPI, but we don't accept credit cards",
        "We don't accept credit cards, but we do accept UPI",
        "Cards are not accepted but UPI is accepted",
        "We accept UPI and cash on delivery is unavailable",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["payment_credibility"] == 1.0, text
        assert out.flags["payment_advantage"] is True, text
        assert out.metrics["payment_advantage_lift"] > 0.0, text


def test_intent_in_unrelated_clause_does_not_void_evidence() -> None:
    for text in (
        "We accept UPI and plan to add COD later",
        "We already accept UPI, though we plan to add EMI",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["payment_credibility"] == 1.0, text
        assert out.flags["payment_advantage"] is True, text
        assert out.metrics["payment_advantage_lift"] > 0.0, text


def test_negation_governs_coordinated_payment_list() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We don't accept UPI and COD"}
        ],
    )
    assert out.metrics["payment_credibility"] < 1.0
    assert out.flags["payment_advantage"] is False
    assert out.flags["cash_dependency_gap"] is True
    assert out.severity == "CRITICAL"


def test_intent_governs_coordinated_payment_list() -> None:
    out = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We plan to add UPI and COD next quarter"}
        ],
    )
    assert out.metrics["payment_credibility"] < 1.0
    assert out.flags["payment_advantage"] is False
    assert out.flags["cash_dependency_gap"] is True
    assert out.severity == "CRITICAL"


def test_working_state_is_evidence_but_working_on_is_intent() -> None:
    working = _compute(
        assumptions=[{"text": "UPI payments are working"}]
    )
    assert working.metrics["payment_credibility"] == 1.0
    assert working.flags["payment_advantage"] is True

    planned = _compute(
        assumptions=[{"text": "We are working on UPI payments"}]
    )
    assert planned.metrics["payment_credibility"] < 1.0
    assert planned.flags["payment_advantage"] is False
    assert planned.metrics["payment_advantage_lift"] == 0.0


# ---------------------------------------------------------------------------
# Markov overrides
# ---------------------------------------------------------------------------


def test_active_gap_overrides_funnel_but_evidence_adds_lift() -> None:
    gap = _compute(
        trust=0.3,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We need to set up UPI and cash on delivery"}
        ],
    )
    overrides = _architect().transition_overrides(gap)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert overrides[("BROWSE", "CONSIDER")] < 1.0
    assert ("DECIDE", "PURCHASE") not in overrides

    evidence = _compute(
        trust=0.2,
        risk=0.7,
        literacy=0.3,
        income=0.2,
        geography="tier3_rural",
        assumptions=[
            {"text": "We accept UPI, debit cards, cash on delivery, and EMI"}
        ],
    )
    evidence_overrides = _architect().transition_overrides(evidence)
    assert ("DECIDE", "PURCHASE") in evidence_overrides
    assert evidence_overrides[("DECIDE", "PURCHASE")] > 1.0


# ---------------------------------------------------------------------------
# Cross-cluster report
# ---------------------------------------------------------------------------


def test_generate_report_handles_empty_outputs() -> None:
    from app.simulation.architects.payment_friction import (
        PaymentFrictionArchitect,
    )

    report = PaymentFrictionArchitect().generate_report([])
    assert report.architect_name == "PaymentFrictionArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"


def test_generate_report_rolls_up_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput
    from app.simulation.architects.payment_friction import (
        PaymentFrictionArchitect,
    )

    outputs = [
        ArchitectOutput(
            architect_name="PaymentFrictionArchitect",
            cluster_id="tier3_rural_cash",
            metrics={},
            flags={"checkout_blocker": True},
            narrative_findings=[],
            severity="CRITICAL",
        ),
        ArchitectOutput(
            architect_name="PaymentFrictionArchitect",
            cluster_id="metro_cards",
            metrics={},
            flags={"payment_method_gap": True},
            narrative_findings=[],
            severity="WARNING",
        ),
    ]
    report = PaymentFrictionArchitect().generate_report(outputs)
    assert report.severity == "CRITICAL"
    assert report.affected_cluster_ids == [
        "tier3_rural_cash",
        "metro_cards",
    ]
    assert "checkout/cash gaps" in report.primary_finding


# ---------------------------------------------------------------------------
# Conductor + calibration registration
# ---------------------------------------------------------------------------


def test_conductor_runs_architect_and_accountability_surfaces_finding() -> None:
    from app.simulation.accountability import AccountabilityEngine
    from app.simulation.conductor import Conductor, ProductType

    result = Conductor().run(
        agents=[],
        env_params={
            "description": "A consumer mobile app with checkout",
            "average_order_value": 499,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "Checkout requires a credit card and no UPI"}
        ],
        product_type=ProductType.MOBILE_APP,
    )
    assert "PaymentFrictionArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "PaymentFrictionArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "PaymentFrictionArchitect"
        for finding in findings
    )


def test_registry_includes_new_architect_in_every_stack() -> None:
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        _build_architect_registry,
    )

    registry = _build_architect_registry()
    assert "PaymentFrictionArchitect" in registry
    for stack in ARCHITECT_STACKS.values():
        assert "PaymentFrictionArchitect" in stack
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "PaymentFrictionArchitect" in ALL_ARCHITECT_NAMES

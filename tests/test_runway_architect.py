"""
Tests for ``app.simulation.architects.runway`` — RunwayArchitect.

Locks down cash-runway / funding-viability signal detection, funding-amount
and explicit-runway parsing, negation- and intent-aware evidence handling,
per-cluster viability sensitivity and severity tiers, Markov transition
overrides, the cross-cluster generate_report() rollup, and conductor,
accountability and calibration registration so the domain surfaces as a
founder finding.
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
    cluster_id: str = "metro_pro",
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
        product_affinities=affinities or ["saas"],
        demographic_profile={"geography": "metro", "age_bracket": "25-35"},
    )


def _compute(
    *,
    trust: float = 0.5,
    risk: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    patience: float = 0.5,
    cluster_id: str = "metro_pro",
    affinities: list[str] | None = None,
    assumptions: list[Any] | None = None,
    agent_profile: dict[str, Any] | None = None,
    product_type: str = "saas",
    env_params: dict[str, Any] | None = None,
) -> Any:
    from app.simulation.architects.runway import RunwayArchitect

    params = {"product_type": product_type, "average_order_value": 999}
    if env_params:
        params.update(env_params)
    return RunwayArchitect().compute(
        cluster=_cluster(
            trust=trust,
            risk=risk,
            literacy=literacy,
            income=income,
            price_sens=price_sens,
            patience=patience,
            cluster_id=cluster_id,
            affinities=affinities,
        ),
        agent_profile=agent_profile or {},
        assumptions=assumptions or [],
        env_params=params,
    )


def _architect() -> Any:
    from app.simulation.architects.runway import RunwayArchitect

    return RunwayArchitect()


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    architect = _architect()
    assert architect.name == "RunwayArchitect"
    assert architect.product_types == []


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "RunwayArchitect"
    assert len(out.metrics) == 7
    assert out.metrics["viability_exposure"] == 0.0
    assert out.metrics["business_health_score"] == 1.0
    assert out.metrics["viability_risk"] == 0.0
    assert out.metrics["runway_funnel_suppressor"] == 1.0
    assert out.metrics["explicit_runway_months"] == 0.0
    assert out.metrics["raised_amount_millions"] == 0.0
    for key, value in out.metrics.items():
        if key not in ("explicit_runway_months", "raised_amount_millions"):
            assert 0.0 <= value <= 1.0
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    out = _compute()
    assert _architect().transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Gap-signal modelling
# ---------------------------------------------------------------------------


def test_bootstrapped_pre_revenue_gap_suppresses_decision() -> None:
    out = _compute(
        risk=0.8,
        trust=0.3,
        assumptions=[
            {
                "text": "We are bootstrapped and pre-revenue, seeking funding"
            }
        ],
    )
    assert out.metrics["viability_exposure"] > 0.0
    assert out.metrics["business_health_score"] <= 0.45
    assert out.metrics["viability_risk"] >= 0.5
    assert out.metrics["runway_funnel_suppressor"] < 0.70
    assert out.flags["runway_gap"] is True
    assert out.flags["viability_critical"] is True
    assert out.flags["funding_evidence"] is False
    assert out.severity == "CRITICAL"

    overrides = _architect().transition_overrides(out)
    assert overrides == {("CONSIDER", "DECIDE"): out.metrics["runway_funnel_suppressor"]}
    assert overrides[("CONSIDER", "DECIDE")] < 1.0


def test_gap_is_warning_for_low_sensitivity_cluster() -> None:
    out = _compute(
        risk=0.1,
        trust=0.9,
        income=0.9,
        patience=0.9,
        assumptions=[
            {"text": "Pre-revenue and looking for investors"}
        ],
    )
    assert out.metrics["viability_sensitivity"] < 0.45
    assert out.metrics["runway_funnel_suppressor"] >= 0.70
    assert out.flags["runway_gap"] is True
    assert out.flags["viability_critical"] is False
    assert out.severity == "WARNING"


def test_short_explicit_runway_is_critical_for_sensitive_cluster() -> None:
    out = _compute(
        risk=0.9,
        trust=0.2,
        income=0.2,
        product_type="health_hardware",
        assumptions=[{"text": "We only have 3 months of runway"}],
    )
    assert out.metrics["explicit_runway_months"] == 3.0
    assert out.metrics["business_health_score"] <= 0.45
    assert out.metrics["runway_funnel_suppressor"] <= 0.55
    assert out.flags["explicit_runway_reported"] is True
    assert out.flags["viability_critical"] is True
    assert out.severity == "CRITICAL"


# ---------------------------------------------------------------------------
# Funding and breakeven evidence
# ---------------------------------------------------------------------------


def test_raised_two_million_is_confirmed_viability() -> None:
    out = _compute(
        assumptions=[{"text": "We raised $2M in a seed round"}],
    )
    assert out.metrics["raised_amount_millions"] == 2.0
    assert out.metrics["business_health_score"] == 0.88
    assert out.metrics["runway_funnel_suppressor"] == 1.0
    assert out.flags["funding_evidence"] is True
    assert out.flags["runway_gap"] is False
    assert out.severity == "INFO"
    assert _architect().transition_overrides(out) == {}


def test_small_inr_raise_is_treated_as_modest() -> None:
    out = _compute(
        assumptions=[{"text": "We raised ₹1 crore in angel funding"}],
    )
    assert 0.10 <= out.metrics["raised_amount_millions"] <= 0.15
    assert out.metrics["business_health_score"] == 0.65
    assert out.metrics["runway_funnel_suppressor"] < 1.0
    assert out.flags["runway_gap"] is True
    assert out.severity == "WARNING"


def test_breakeven_evidence_is_strongest_health_signal() -> None:
    out = _compute(
        assumptions=[
            {
                "text": "We are revenue positive with paying customers "
                "and recurring subscription revenue"
            }
        ],
    )
    assert out.metrics["business_health_score"] == 0.95
    assert out.metrics["runway_funnel_suppressor"] == 1.0
    assert out.flags["break_even_reached"] is True
    assert out.flags["runway_gap"] is False
    assert out.severity == "INFO"


def test_discourse_negation_preserves_breakeven_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "No, we are already profitable"}],
    )
    assert out.flags["break_even_reached"] is True
    assert out.metrics["business_health_score"] == 0.95


def test_not_yet_profitable_is_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We are not yet profitable"}],
    )
    assert out.flags["break_even_reached"] is False
    assert out.flags["funding_evidence"] is False
    assert out.metrics["business_health_score"] == 1.0
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Amount and runway parsing
# ---------------------------------------------------------------------------


def test_amount_parsing_handles_currency_units() -> None:
    cases = [
        ("We raised $2M in seed funding", 2.0),
        ("We secured funding of $500k", 0.5),
        ("We raised 2 million from angels", 2.0),
        ("We raised ₹50 lakh", 0.06),
    ]
    for text, expected in cases:
        out = _compute(assumptions=[{"text": text}])
        assert abs(out.metrics["raised_amount_millions"] - expected) < 1e-6, text


def test_runway_month_parsing_formats() -> None:
    cases = [
        ("We have 18 months of runway", 18.0, 0.85),
        ("runway of 12 months remains", 12.0, 0.75),
        ("6-9 months of cash runway left", 9.0, 0.58),
        ("Our runway is 18 months", 18.0, 0.85),
        ("Our runway stands at 12 months", 12.0, 0.75),
        ("Our runway is 6 months", 6.0, 0.58),
    ]
    for text, months, health in cases:
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["explicit_runway_months"] == months, text
        assert out.metrics["business_health_score"] == health, text
        assert out.flags["explicit_runway_reported"] is True


def test_intent_voids_runway_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We will have 18 months of runway after closing"}],
    )
    assert out.metrics["explicit_runway_months"] == 0.0
    assert out.flags["explicit_runway_reported"] is False
    assert out.metrics["business_health_score"] == 1.0


def test_voided_funding_claim_counts_as_gap() -> None:
    out = _compute(
        assumptions=[{"text": "We have not raised funding yet"}],
    )
    assert out.flags["funding_evidence"] is False
    assert out.metrics["business_health_score"] <= 0.45
    assert out.flags["runway_gap"] is True


def test_self_funded_is_a_gap_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We are self-funded"}],
    )
    assert out.flags["funding_evidence"] is False
    assert out.metrics["business_health_score"] <= 0.45
    assert out.flags["runway_gap"] is True


def test_bootstrapped_but_profitable_keeps_breakeven_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We are bootstrapped and profitable"}],
    )
    assert out.flags["break_even_reached"] is True
    assert out.metrics["business_health_score"] == 0.95
    assert out.flags["runway_gap"] is False


def test_trailing_intent_clause_does_not_void_raised_evidence() -> None:
    for text in (
        "We raised $2M to build the product",
        "We raised $2M because we need to hire",
        "We raised $2M in order to build",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["raised_amount_millions"] == 2.0, text
        assert out.metrics["business_health_score"] == 0.88, text
        assert out.flags["funding_evidence"] is True, text
        assert out.flags["runway_gap"] is False, text


def test_trailing_intent_clause_does_not_void_runway_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "We have 12 months of runway to build the product"}],
    )
    assert out.metrics["explicit_runway_months"] == 12.0
    assert out.metrics["business_health_score"] == 0.75
    assert out.flags["explicit_runway_reported"] is True


def test_trailing_intent_clause_does_not_void_breakeven_evidence() -> None:
    for text in (
        "We are profitable because we plan to expand",
        "We are profitable because we need cash flow",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.flags["break_even_reached"] is True, text
        assert out.metrics["business_health_score"] == 0.95, text


def test_question_clauses_are_not_evidence() -> None:
    for text in (
        "Are you profitable?",
        "How much have we raised?",
        "Profitable? We aim to be profitable",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.flags["break_even_reached"] is False, text
        assert out.flags["funding_evidence"] is False, text
        assert out.metrics["business_health_score"] == 1.0, text


def test_fundraising_intent_is_a_gap() -> None:
    out = _compute(
        risk=0.1,
        trust=0.9,
        income=0.9,
        patience=0.9,
        assumptions=[{"text": "We plan to raise a seed round next quarter"}],
    )
    assert out.flags["funding_evidence"] is False
    assert out.flags["runway_gap"] is True
    assert out.metrics["business_health_score"] <= 0.45
    assert out.severity == "WARNING"


def test_common_gap_phrasings_are_detected() -> None:
    for text in (
        "We need to raise $2M",
        "We plan to raise $2M next quarter",
        "We are seeking pre-seed funding",
        "We require funding to grow",
        "We lack funding",
        "We are out of cash",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.flags["funding_evidence"] is False, text
        assert out.flags["runway_gap"] is True, text
        assert out.metrics["business_health_score"] <= 0.45, text


# ---------------------------------------------------------------------------
# Sensitivity modelling
# ---------------------------------------------------------------------------


def test_sensitivity_rises_with_risk_aversion_and_low_trust() -> None:
    low = _compute(risk=0.1, trust=0.9, income=0.9, patience=0.9)
    high = _compute(risk=0.9, trust=0.1, income=0.1, patience=0.1)
    assert low.metrics["viability_sensitivity"] < high.metrics["viability_sensitivity"]


def test_high_ticket_product_raises_sensitivity() -> None:
    low = _compute(
        product_type="saas",
        env_params={"average_order_value": 999},
    )
    high = _compute(
        product_type="saas",
        env_params={"average_order_value": 50000},
    )
    assert low.metrics["viability_sensitivity"] < high.metrics["viability_sensitivity"]


def test_longevity_product_raises_sensitivity() -> None:
    saas = _compute(product_type="saas")
    hardware = _compute(product_type="health_hardware")
    assert saas.metrics["viability_sensitivity"] < hardware.metrics["viability_sensitivity"]


def test_suppressor_has_floor() -> None:
    out = _compute(
        risk=0.95,
        trust=0.05,
        income=0.05,
        patience=0.05,
        product_type="b2b_hardware",
        assumptions=[{"text": "We are out of money and burning cash"}],
    )
    assert out.metrics["runway_funnel_suppressor"] >= 0.40


# ---------------------------------------------------------------------------
# Transition overrides
# ---------------------------------------------------------------------------


def test_overrides_only_apply_when_viability_gap_active() -> None:
    architect = _architect()
    gap = _compute(
        assumptions=[{"text": "Pre-revenue, low runway"}],
    )
    overrides = architect.transition_overrides(gap)
    assert set(overrides.keys()) == {("CONSIDER", "DECIDE")}
    assert 0.0 < overrides[("CONSIDER", "DECIDE")] <= 1.0

    healthy = _compute(
        assumptions=[{"text": "We raised $2M"}],
    )
    assert architect.transition_overrides(healthy) == {}


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    report = _architect().generate_report([])
    assert report.architect_name == "RunwayArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.population_fraction == 0.0
    assert report.conversion_impact == 0.0


def test_generate_report_aggregates_critical_and_warning_clusters() -> None:
    from app.simulation.architects.base import ArchitectOutput

    architect = _architect()
    critical = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="metro_pro",
        metrics={},
        flags={"viability_critical": True, "runway_gap": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    warning = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="rural_medical",
        metrics={},
        flags={"viability_critical": False, "runway_gap": True},
        narrative_findings=[],
        severity="WARNING",
    )
    report = architect.generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert set(report.affected_cluster_ids) == {"metro_pro", "rural_medical"}
    assert report.conversion_impact > 0.0
    assert "runway" in report.recommended_action.lower()


# ---------------------------------------------------------------------------
# Conductor + accountability integration
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
                "text": "We are pre-revenue, bootstrapped and seeking funding"
            }
        ],
        product_type=ProductType.SAAS,
    )
    assert "RunwayArchitect" in result.cluster_results["metro_power_professional"]
    assert any(
        report.architect_name == "RunwayArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "RunwayArchitect"
        for finding in findings
    )


def test_registry_includes_architect_in_every_product_stack() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
        ProductType,
    )

    registry = build_architect_registry()
    assert "RunwayArchitect" in registry
    for product_type in ProductType:
        stack = ARCHITECT_STACKS[product_type]
        assert "RunwayArchitect" in stack
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "RunwayArchitect" in ALL_ARCHITECT_NAMES


def test_accountability_benchmarks_cover_runway_metrics() -> None:
    from app.simulation.accountability import AccountabilityEngine

    benchmarks = AccountabilityEngine.HEALTHY_BENCHMARKS
    for metric in (
        "viability_exposure",
        "business_health_score",
        "viability_risk",
        "runway_funnel_suppressor",
    ):
        assert metric in benchmarks
        assert metric in AccountabilityEngine.FINDING_TEMPLATES
        assert metric in AccountabilityEngine.RECOMMENDED_ACTIONS

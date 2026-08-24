"""
Tests for ``app.simulation.architects.supply_chain`` —
SupplyChainArchitect.

Locks down hardware component-sourcing exposure detection,
single-source concentration risk, stockout/tariff modelling,
negation- and intent-aware evidence handling, severity tiers, flags,
narrative findings, Markov transition overrides, the cross-cluster
generate_report() rollup, and conductor/calibration registration so
supply-chain risk surfaces as an accountability finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    patience: float = 0.5,
    income: float = 0.5,
    risk: float = 0.5,
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
            "digital_literacy": 0.5,
            "motivation": 0.5,
            "trust": 0.5,
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
        product_affinities=["consumer_hardware"],
        demographic_profile={"geography": "metro", "age_bracket": "25-35"},
    )


def _compute(
    *,
    patience: float = 0.5,
    income: float = 0.5,
    risk: float = 0.5,
    price_sens: float = 0.5,
    cluster_id: str = "metro_power_professional",
    assumptions: list[Any] | None = None,
    product_type: str = "consumer_hardware",
) -> Any:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    return SupplyChainArchitect().compute(
        cluster=_cluster(
            patience=patience,
            income=income,
            risk=risk,
            price_sens=price_sens,
            cluster_id=cluster_id,
        ),
        agent_profile={},
        assumptions=assumptions or [],
        env_params={"product_type": product_type},
    )


# ---------------------------------------------------------------------------
# Identity + baseline behaviour
# ---------------------------------------------------------------------------


def test_name_and_product_types() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    architect = SupplyChainArchitect()
    assert architect.name == "SupplyChainArchitect"
    assert architect.product_types == [
        "consumer_hardware", "health_hardware", "iot_hardware",
        "wearable", "b2b_hardware", "smart_home",
    ]


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "SupplyChainArchitect"
    assert len(out.metrics) == 9
    assert out.metrics["supply_chain_exposure"] == 0.12
    assert out.metrics["funnel_suppressor"] == 1.0
    assert out.metrics["supply_chain_advantage_lift"] == 0.0
    assert abs(out.metrics["supply_chain_credibility"] - 0.898) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    architect = SupplyChainArchitect()
    out = _compute()
    assert architect.transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Signal detection and risk modelling
# ---------------------------------------------------------------------------


def test_chain_mention_flags_stockout_gap_for_impatient_cluster() -> None:
    out = _compute(
        patience=0.3,
        income=0.3,
        assumptions=[
            {"text": "We manufacture a smart speaker with custom "
                     "components and a long lead time"}
        ],
    )
    assert out.metrics["supply_chain_exposure"] == 0.48
    assert out.metrics["stockout_risk"] >= 0.35
    assert out.metrics["sourcing_risk"] > 0.20
    assert out.flags["stockout_gap"] is True
    assert out.flags["single_source_blocker"] is False
    assert out.severity == "WARNING"


def test_single_supplier_language_flags_critical_blocker() -> None:
    out = _compute(
        patience=0.3,
        income=0.3,
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"}
        ],
    )
    assert out.metrics["single_source_dependency"] >= 0.55
    assert out.metrics["sourcing_risk"] >= 0.55
    assert out.flags["single_source_blocker"] is True
    assert out.flags["sourcing_gap"] is True
    assert out.severity == "CRITICAL"


def test_mitigation_plan_lowers_sourcing_risk_without_clearing_blocker() -> None:
    blocker_only = _compute(
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"},
        ],
    )
    out = _compute(
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"},
            {"text": "We will use dual sourcing and local manufacturing"},
        ],
    )
    assert out.metrics["lead_time_risk"] < blocker_only.metrics["lead_time_risk"]
    assert out.metrics["stockout_risk"] < blocker_only.metrics["stockout_risk"]
    assert out.flags["single_source_blocker"] is True
    assert out.severity == "CRITICAL"


def test_tariff_language_flags_logistics_gap() -> None:
    out = _compute(
        assumptions=[
            {"text": "Import duties and tariffs will hurt our margins"}
        ],
    )
    assert out.metrics["logistics_tariff_risk"] >= 0.5
    assert out.flags["logistics_tariff_gap"] is True
    assert out.severity == "WARNING"


# ---------------------------------------------------------------------------
# Evidence handling
# ---------------------------------------------------------------------------


def test_evidence_clears_blocker_and_raises_credibility() -> None:
    out = _compute(
        patience=0.3,
        income=0.3,
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"},
            {"text": "We have signed supplier contracts, purchase orders "
                     "issued, and the pilot run produced units"},
        ],
    )
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["single_source_blocker"] is False
    assert out.flags["sourcing_gap"] is False
    assert out.flags["stockout_gap"] is False
    assert out.flags["supply_chain_advantage"] is True
    assert out.metrics["supply_chain_advantage_lift"] > 0.0
    assert out.metrics["single_source_dependency"] < 0.1
    assert out.severity == "INFO"


def test_negated_evidence_is_not_proof() -> None:
    out = _compute(
        assumptions=[
            {"text": "No supplier contracts signed yet and supply not secured"}
        ],
    )
    assert out.metrics["supply_chain_credibility"] < 1.0
    assert out.flags["supply_chain_advantage"] is False
    assert out.metrics["supply_chain_advantage_lift"] == 0.0


def test_intent_language_is_not_proof() -> None:
    out = _compute(
        assumptions=[
            {"text": "We plan to secure suppliers and will issue "
                     "purchase orders soon"}
        ],
    )
    assert out.metrics["supply_chain_credibility"] < 1.0
    assert out.flags["supply_chain_advantage"] is False
    assert out.metrics["supply_chain_advantage_lift"] == 0.0


def test_discourse_negation_keeps_real_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "No, we already have suppliers signed and "
                     "purchase orders issued"}
        ],
    )
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["supply_chain_advantage"] is True
    assert out.metrics["supply_chain_advantage_lift"] > 0.0


def test_copular_evidence_variants_are_recognized() -> None:
    out = _compute(
        assumptions=[
            {"text": "Our MOQ is met, supplier contracts are signed, "
                     "and purchase orders have been issued"}
        ],
    )
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["supply_chain_advantage"] is True
    assert out.metrics["supply_chain_advantage_lift"] > 0.0
    assert out.flags["single_source_blocker"] is False
    assert out.severity == "INFO"


def test_evidence_only_mention_activates_advantage() -> None:
    out = _compute(
        assumptions=[
            {"text": "Orders shipped last week"},
        ],
    )
    assert out.metrics["supply_chain_exposure"] > 0.15
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["supply_chain_advantage"] is True
    assert out.metrics["supply_chain_advantage_lift"] > 0.0
    assert out.severity == "INFO"


def test_units_have_been_produced_is_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "Units have been produced in the pilot run"},
        ],
    )
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["supply_chain_advantage"] is True


def test_aspirational_hedges_are_not_evidence() -> None:
    for text in (
        "Initial production expected in Q3",
        "We are almost production ready",
        "MOQ is expected to be met in Q2",
        "Production line probably ready next month",
    ):
        out = _compute(assumptions=[{"text": text}])
        assert out.metrics["supply_chain_credibility"] < 1.0, text
        assert out.flags["supply_chain_advantage"] is False, text
        assert out.metrics["supply_chain_advantage_lift"] == 0.0, text


def test_negation_scope_stops_at_coordinate_phrase() -> None:
    out = _compute(
        assumptions=[
            {"text": "Supplier contracts are signed and no debt remains"},
        ],
    )
    assert out.metrics["supply_chain_credibility"] == 1.0
    assert out.flags["supply_chain_advantage"] is True


def test_negated_copular_evidence_is_gap() -> None:
    out = _compute(
        assumptions=[
            {"text": "No supplier contracts are signed and no purchase "
                     "orders are issued"}
        ],
    )
    assert out.metrics["supply_chain_credibility"] < 1.0
    assert out.flags["supply_chain_advantage"] is False
    assert out.metrics["supply_chain_advantage_lift"] == 0.0


def test_single_supplier_with_no_backup_is_still_blocker() -> None:
    out = _compute(
        assumptions=[
            {"text": "We rely on a single supplier with no backup"},
        ],
    )
    assert out.metrics["single_source_dependency"] >= 0.55
    assert out.flags["single_source_blocker"] is True
    assert out.severity == "CRITICAL"


def test_neutral_lead_time_mention_is_not_risk_language() -> None:
    neutral = _compute(
        assumptions=[
            {"text": "Our lead time is two weeks from order"},
        ],
    )
    long = _compute(
        patience=0.3,
        assumptions=[
            {"text": "We have a long lead time on components"},
        ],
    )
    assert neutral.metrics["supply_chain_exposure"] == 0.30
    assert neutral.metrics["lead_time_risk"] < long.metrics["lead_time_risk"]
    assert neutral.flags["sourcing_gap"] is False
    assert neutral.flags["stockout_gap"] is False
    assert neutral.severity == "INFO"
    assert long.flags["stockout_gap"] is True
    assert long.severity == "WARNING"


# ---------------------------------------------------------------------------
# Markov transition overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_suppress_when_exposure_active() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    architect = SupplyChainArchitect()
    out = _compute(
        patience=0.3,
        assumptions=[
            {"text": "We manufacture a smart speaker with custom "
                     "components and a long lead time"}
        ],
    )
    overrides = architect.transition_overrides(out)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") not in overrides
    assert 0.55 <= overrides[("BROWSE", "CONSIDER")] < 1.0


def test_transition_overrides_add_purchase_lift_when_evidence_exists() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    architect = SupplyChainArchitect()
    out = _compute(
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"},
            {"text": "We have signed supplier contracts and the pilot "
                     "run produced units"},
        ],
    )
    overrides = architect.transition_overrides(out)
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("DECIDE", "PURCHASE")] > 1.0


# ---------------------------------------------------------------------------
# generate_report rollup
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    report = SupplyChainArchitect().generate_report([])
    assert report.architect_name == "SupplyChainArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.conversion_impact == 0.0


def test_generate_report_rolls_up_critical_and_warning_clusters() -> None:
    from app.simulation.architects.supply_chain import SupplyChainArchitect

    critical = _compute(
        patience=0.3,
        income=0.3,
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor"}
        ],
    )
    warning = _compute(
        cluster_id="tier3_first_time_app_user",
        patience=0.3,
        assumptions=[
            {"text": "We manufacture a smart speaker with custom "
                     "components and a long lead time"}
        ],
    )
    report = SupplyChainArchitect().generate_report([critical, warning])
    assert report.severity == "CRITICAL"
    assert report.affected_cluster_ids == [
        "metro_power_professional",
        "tier3_first_time_app_user",
    ]
    assert report.population_fraction > 0.0
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
            "description": "A smart speaker hardware gadget",
            "average_order_value": 4_999,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "We rely on a single supplier for the main sensor "
                     "and have a long lead time"}
        ],
        product_type=ProductType.CONSUMER_HARDWARE,
    )
    assert "SupplyChainArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "SupplyChainArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "SupplyChainArchitect"
        for finding in findings
    )


def test_registry_activates_architect_for_hardware_stacks_only() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.architects.supply_chain import SupplyChainArchitect
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
    )
    from app.simulation.product_type import ProductType

    registry = build_architect_registry()
    assert "SupplyChainArchitect" in registry
    activated = {
        pt.value
        for pt, stack in ARCHITECT_STACKS.items()
        if "SupplyChainArchitect" in stack
        and pt.value in SupplyChainArchitect().product_types
    }
    assert activated == set(SupplyChainArchitect().product_types)
    assert "SupplyChainArchitect" not in ARCHITECT_STACKS[ProductType.SAAS]
    for product_type in (
        ProductType.CONSUMER_HARDWARE,
        ProductType.HEALTH_HARDWARE,
        ProductType.IOT_HARDWARE,
        ProductType.WEARABLE,
        ProductType.B2B_HARDWARE,
        ProductType.SMART_HOME,
    ):
        assert (
            "SupplyChainArchitect" in ARCHITECT_STACKS[product_type]
        )
        assert ARCHITECT_STACKS[product_type][-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "SupplyChainArchitect" in ALL_ARCHITECT_NAMES

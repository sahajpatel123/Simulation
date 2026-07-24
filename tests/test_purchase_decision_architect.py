"""Focused tests for hardware purchase-decision behavior."""
from __future__ import annotations

from typing import Any

from app.simulation.architects.base import ArchitectOutput
from app.simulation.architects.purchase_decision import PurchaseDecisionArchitect
from app.simulation.clusters.definitions import ClusterDefinition


def _cluster(
    *,
    cluster_id: str = "health_hardware_enthusiast",
    income: float = 0.5,
    literacy: float = 0.7,
    price_sensitivity: float = 0.5,
    risk_aversion: float = 0.5,
    age_bracket: str = "25-35",
) -> Any:
    traits = {
        "income_level": income,
        "digital_literacy": literacy,
        "motivation": 0.6,
        "trust": 0.6,
        "price_sensitivity": price_sensitivity,
        "risk_aversion": risk_aversion,
        "patience_score": 0.5,
        "social_orientation": 0.5,
    }
    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test",
        description="Test",
        population_weight=0.1,
        base_traits=traits,
        trait_variance={key: 0.05 for key in traits},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["health_hardware"],
        demographic_profile={
            "geography": "metro_delhi",
            "age_bracket": age_bracket,
        },
    )


def _compute(
    *,
    cluster: Any | None = None,
    assumptions: list[dict[str, Any]] | None = None,
    agent_profile: dict[str, Any] | None = None,
    aov: float = 8_000,
) -> ArchitectOutput:
    return PurchaseDecisionArchitect().compute(
        cluster=cluster or _cluster(),
        agent_profile=agent_profile or {},
        assumptions=assumptions or [],
        env_params={"average_order_value": aov, "product_type": "health_hardware"},
    )


def test_plain_simple_language_does_not_enable_bnpl() -> None:
    output = _compute(
        assumptions=[{"text": "The product should have a simple setup experience"}],
        cluster=_cluster(age_bracket="18-24"),
    )

    assert output.metrics["bnpl_likelihood"] == 0.0


def test_simpl_provider_enables_bnpl() -> None:
    output = _compute(
        assumptions=[{"text": "Checkout supports Simpl payments"}],
        cluster=_cluster(age_bracket="18-24"),
    )

    assert output.metrics["bnpl_likelihood"] > 0.0


def test_semiconductor_text_does_not_enable_emi() -> None:
    output = _compute(
        assumptions=[{"text": "The semiconductor sensor is efficient"}],
    )

    assert output.metrics["emi_adoption_likelihood"] == 0.0


def test_buy_now_pay_later_enables_bnpl() -> None:
    output = _compute(
        assumptions=[{"text": "Buy now pay later is available at checkout"}],
    )

    assert output.metrics["bnpl_likelihood"] > 0.0


def test_emi_increases_will_pay_probability_when_price_exceeds_ceiling() -> None:
    cluster = _cluster(income=0.2, price_sensitivity=0.9)
    without_emi = _compute(cluster=cluster, aov=20_000)
    with_emi = _compute(
        cluster=cluster,
        assumptions=[{"text": "No-cost EMI is available"}],
        aov=20_000,
    )

    assert with_emi.metrics["emi_adoption_likelihood"] > 0.0
    assert with_emi.metrics["will_pay_probability"] > without_emi.metrics["will_pay_probability"]
    assert with_emi.flags["price_kill_shot"] is False


def test_extended_return_policy_improves_conversion_effect() -> None:
    seven_day = _compute()
    thirty_day = _compute(
        assumptions=[{"text": "Customers receive a 30-day return policy"}],
    )

    assert (
        thirty_day.metrics["return_policy_conversion_effect"]
        > seven_day.metrics["return_policy_conversion_effect"]
    )


def test_transition_overrides_are_bounded_probabilities() -> None:
    architect = PurchaseDecisionArchitect()
    output = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="test",
        metrics={
            "will_pay_probability": 2.0,
            "emi_adoption_likelihood": 2.0,
            "return_policy_conversion_effect": 2.0,
        },
        flags={},
        narrative_findings=[],
        severity="INFO",
    )

    overrides = architect.transition_overrides(output)

    assert set(overrides) == {
        ("BROWSE", "CONSIDER"),
        ("CONSIDER", "DECIDE"),
        ("DECIDE", "PURCHASE"),
    }
    assert all(0.05 <= probability <= 0.95 for probability in overrides.values())


def test_generate_report_identifies_price_kill_shot_clusters() -> None:
    architect = PurchaseDecisionArchitect()
    blocked = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="blocked",
        metrics={},
        flags={"price_kill_shot": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    affordable = ArchitectOutput(
        architect_name=architect.name,
        cluster_id="affordable",
        metrics={},
        flags={"price_kill_shot": False},
        narrative_findings=[],
        severity="INFO",
    )

    report = architect.generate_report([blocked, affordable])

    assert report.severity == "CRITICAL"
    assert report.affected_cluster_ids == ["blocked"]
    assert "EMI" in report.recommended_action


def test_generate_report_handles_empty_outputs() -> None:
    report = PurchaseDecisionArchitect().generate_report([])

    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []

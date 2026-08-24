"""
Tests for ``app.simulation.architects.marketplace_liquidity`` —
MarketplaceLiquidityArchitect.

Locks down liquidity/cold-start signal detection, supply/demand side risk,
negation-aware evidence handling, severity tiers, flags, narrative findings,
Markov transition overrides, and the cross-cluster generate_report() rollup —
plus conductor and calibration registration so the new domain actually
surfaces as an accountability finding.
"""

from __future__ import annotations

from typing import Any


def _cluster(
    *,
    trust: float = 0.5,
    price_sens: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
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
            "risk_aversion": 0.5,
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
        product_affinities=["marketplace"],
        demographic_profile={"geography": "metro", "age_bracket": "25-35"},
    )


def _compute(
    *,
    trust: float = 0.5,
    price_sens: float = 0.5,
    literacy: float = 0.5,
    income: float = 0.5,
    cluster_id: str = "metro_power_professional",
    assumptions: list[Any] | None = None,
    product_type: str = "marketplace",
) -> Any:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    return MarketplaceLiquidityArchitect().compute(
        cluster=_cluster(
            trust=trust,
            price_sens=price_sens,
            literacy=literacy,
            income=income,
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
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    architect = MarketplaceLiquidityArchitect()
    assert architect.name == "MarketplaceLiquidityArchitect"
    assert architect.product_types == ["marketplace", "b2b_marketplace"]


def test_baseline_compute_is_neutral_and_bounded() -> None:
    out = _compute()
    assert out.architect_name == "MarketplaceLiquidityArchitect"
    assert len(out.metrics) == 8
    assert out.metrics["marketplace_liquidity_exposure"] == 0.12
    assert out.metrics["funnel_suppressor"] == 1.0
    assert out.metrics["liquidity_advantage_lift"] == 0.0
    assert abs(out.metrics["liquidity_credibility"] - 0.898) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert not any(out.flags.values())
    assert out.severity == "INFO"
    assert len(out.narrative_findings) == 2


def test_no_signals_means_no_transition_overrides() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    architect = MarketplaceLiquidityArchitect()
    out = _compute()
    assert architect.transition_overrides(out) == {}


# ---------------------------------------------------------------------------
# Signal detection and side-risk modelling
# ---------------------------------------------------------------------------


def test_liquidity_mention_alone_flags_both_side_gaps() -> None:
    out = _compute(
        assumptions=[{"text": "We depend on network effects and critical mass"}]
    )
    assert out.metrics["marketplace_liquidity_exposure"] == 0.32
    assert out.metrics["cold_start_risk"] > 0.20
    assert out.metrics["supply_side_risk"] >= 0.35
    assert out.metrics["demand_side_risk"] >= 0.35
    assert out.flags["supply_side_gap"] is True
    assert out.flags["demand_side_gap"] is True
    assert out.flags["cold_start_blocker"] is False
    assert out.severity == "WARNING"


def test_supply_plan_lowers_supply_risk_but_not_demand_risk() -> None:
    out = _compute(
        assumptions=[{"text": "We will onboard sellers and build inventory"}]
    )
    assert out.metrics["supply_side_risk"] < 0.35
    assert out.metrics["demand_side_risk"] >= 0.35
    assert out.flags["supply_side_gap"] is False
    assert out.flags["demand_side_gap"] is True
    assert out.severity == "WARNING"


def test_two_sided_plans_without_evidence_block_low_trust_cluster() -> None:
    out = _compute(
        trust=0.2,
        price_sens=0.8,
        literacy=0.4,
        income=0.3,
        assumptions=[
            {"text": "We need to onboard sellers and recruit buyers"}
        ],
    )
    assert out.metrics["marketplace_liquidity_exposure"] == 0.52
    assert out.metrics["cold_start_risk"] >= 0.55
    assert out.flags["cold_start_blocker"] is True
    assert out.flags["liquidity_advantage"] is False
    assert out.metrics["liquidity_advantage_lift"] == 0.0
    assert out.severity == "CRITICAL"


# ---------------------------------------------------------------------------
# Evidence handling
# ---------------------------------------------------------------------------


def test_evidence_clears_blocker_and_raises_credibility() -> None:
    out = _compute(
        trust=0.2,
        price_sens=0.8,
        literacy=0.4,
        income=0.3,
        assumptions=[
            {"text": "We need to onboard sellers and recruit buyers"},
            {"text": "We have signed up sellers and a buyer waitlist with pre-orders"},
        ],
    )
    assert out.metrics["liquidity_credibility"] == 1.0
    assert out.flags["cold_start_blocker"] is False
    assert out.flags["supply_side_gap"] is False
    assert out.flags["demand_side_gap"] is False
    assert out.flags["liquidity_advantage"] is True
    assert out.metrics["liquidity_advantage_lift"] > 0.0
    assert out.metrics["cold_start_risk"] < 0.35
    assert out.severity == "INFO"


def test_negative_liquidity_language_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "No sellers signed up yet and no buyer waitlist"}
        ]
    )
    assert out.metrics["liquidity_credibility"] < 1.0
    assert out.flags["liquidity_advantage"] is False
    assert out.metrics["liquidity_advantage_lift"] == 0.0
    assert out.flags["supply_side_gap"] is True
    assert out.flags["demand_side_gap"] is True
    assert out.severity == "WARNING"


def test_unconfirmed_preorders_are_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {"text": "Pre-orders are not confirmed and no buyers are committed"}
        ]
    )
    assert out.metrics["liquidity_credibility"] < 1.0
    assert out.flags["liquidity_advantage"] is False


def test_contracted_negation_is_not_evidence() -> None:
    out = _compute(
        assumptions=[
            {
                "text": "We don't have a buyer waitlist and "
                "we haven't signed up sellers"
            }
        ]
    )
    assert out.metrics["liquidity_credibility"] < 1.0
    assert out.metrics["liquidity_advantage_lift"] == 0.0
    assert out.flags["liquidity_advantage"] is False
    assert out.flags["supply_side_gap"] is True
    assert out.flags["demand_side_gap"] is True


def test_contracted_negation_preorders_are_not_evidence() -> None:
    out = _compute(
        assumptions=[{"text": "Pre-orders aren't confirmed yet"}]
    )
    assert out.metrics["liquidity_credibility"] < 1.0
    assert out.flags["liquidity_advantage"] is False
    assert out.metrics["liquidity_advantage_lift"] == 0.0


def test_discourse_negation_does_not_void_evidence() -> None:
    out = _compute(
        assumptions=[
            {
                "text": "No, we already have sellers signed up "
                "and a buyer waitlist"
            }
        ]
    )
    assert out.metrics["liquidity_credibility"] == 1.0
    assert out.flags["liquidity_advantage"] is True
    assert out.metrics["liquidity_advantage_lift"] > 0.0
    assert out.flags["supply_side_gap"] is False
    assert out.flags["demand_side_gap"] is False


def test_discourse_negation_with_real_gap_is_still_a_gap() -> None:
    out = _compute(
        assumptions=[
            {"text": "No, we do not have sellers signed up or a waitlist"}
        ]
    )
    assert out.metrics["liquidity_credibility"] < 1.0
    assert out.flags["liquidity_advantage"] is False
    assert out.metrics["liquidity_advantage_lift"] == 0.0


# ---------------------------------------------------------------------------
# Malformed inputs
# ---------------------------------------------------------------------------


def test_compute_handles_malformed_traits_and_missing_assumptions() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    architect = MarketplaceLiquidityArchitect()
    out = architect.compute(
        cluster=_cluster(trust=0.5),
        agent_profile={"trust": "not-a-number"},
        assumptions=[{"text": None}, "plain string assumption"],
        env_params={"product_type": "marketplace"},
    )
    assert all(0.0 <= value <= 1.0 for value in out.metrics.values())
    assert out.severity in {"INFO", "WARNING", "CRITICAL"}


# ---------------------------------------------------------------------------
# Markov transition overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_suppress_funnel_when_gap_active() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    architect = MarketplaceLiquidityArchitect()
    out = _compute(
        assumptions=[{"text": "We depend on network effects and critical mass"}]
    )
    overrides = architect.transition_overrides(out)
    assert ("BROWSE", "CONSIDER") in overrides
    assert ("CONSIDER", "DECIDE") in overrides
    assert ("DECIDE", "PURCHASE") not in overrides
    assert 0.55 <= overrides[("BROWSE", "CONSIDER")] < 1.0


def test_transition_overrides_add_purchase_lift_when_evidence_exists() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    architect = MarketplaceLiquidityArchitect()
    out = _compute(
        assumptions=[
            {"text": "We need to onboard sellers and recruit buyers"},
            {"text": "We have signed up sellers and a buyer waitlist with pre-orders"},
        ],
    )
    overrides = architect.transition_overrides(out)
    assert ("DECIDE", "PURCHASE") in overrides
    assert overrides[("DECIDE", "PURCHASE")] > 1.0


# ---------------------------------------------------------------------------
# generate_report rollup
# ---------------------------------------------------------------------------


def test_generate_report_empty_outputs_is_graceful() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    report = MarketplaceLiquidityArchitect().generate_report([])
    assert report.architect_name == "MarketplaceLiquidityArchitect"
    assert report.affected_cluster_ids == []
    assert report.severity == "INFO"
    assert report.conversion_impact == 0.0


def test_generate_report_rolls_up_critical_and_warning_clusters() -> None:
    from app.simulation.architects.marketplace_liquidity import (
        MarketplaceLiquidityArchitect,
    )

    critical = _compute(
        trust=0.2,
        price_sens=0.8,
        literacy=0.4,
        income=0.3,
        assumptions=[
            {"text": "We need to onboard sellers and recruit buyers"}
        ],
    )
    warning = _compute(
        cluster_id="tier3_first_time_app_user",
        assumptions=[{"text": "We depend on network effects and critical mass"}],
    )
    report = MarketplaceLiquidityArchitect().generate_report(
        [critical, warning]
    )
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
            "description": "A two-sided marketplace for freelance services",
            "average_order_value": 499,
            "market_maturity": 0.5,
        },
        assumptions=[
            {"text": "We need to onboard sellers and recruit buyers"}
        ],
        product_type=ProductType.MARKETPLACE,
    )
    assert "MarketplaceLiquidityArchitect" in result.cluster_results[
        "metro_power_professional"
    ]
    assert any(
        report.architect_name == "MarketplaceLiquidityArchitect"
        for report in result.domain_reports
    )
    findings = AccountabilityEngine().generate_domain_findings(result)
    assert any(
        finding.architect_name == "MarketplaceLiquidityArchitect"
        for finding in findings
    )


def test_registry_activates_architect_for_marketplace_stacks_only() -> None:
    from app.simulation.architect_registry import build_architect_registry
    from app.simulation.conductor import (
        ARCHITECT_STACKS,
    )
    from app.simulation.product_type import ProductType

    registry = build_architect_registry()
    assert "MarketplaceLiquidityArchitect" in registry
    assert (
        "MarketplaceLiquidityArchitect"
        in ARCHITECT_STACKS[ProductType.MARKETPLACE]
    )
    assert (
        "MarketplaceLiquidityArchitect"
        in ARCHITECT_STACKS[ProductType.B2B_MARKETPLACE]
    )
    assert (
        "MarketplaceLiquidityArchitect"
        not in ARCHITECT_STACKS[ProductType.SAAS]
    )
    for stack in (
        ARCHITECT_STACKS[ProductType.MARKETPLACE],
        ARCHITECT_STACKS[ProductType.B2B_MARKETPLACE],
    ):
        assert stack[-1] == "AssumptionCascadeArchitect"


def test_registered_in_calibration() -> None:
    from app.simulation.calibration_engine import ALL_ARCHITECT_NAMES

    assert "MarketplaceLiquidityArchitect" in ALL_ARCHITECT_NAMES

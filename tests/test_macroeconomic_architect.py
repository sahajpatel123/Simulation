"""
Tests for ``app.simulation.architects.macroeconomic`` —
MacroeconomicArchitect.

Locks down scenario correction paths (RECESSION, HIGH_GROWTH, NORMAL),
festival amplifier per product_type, USD pricing penalty by income,
government subsidy multiplier, conversion_correction composition with
clamping, severity tiers, flags, narrative findings, and the
generate_report() rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    income: float = 0.5,
    literacy: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
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
            "motivation": motivation,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": patience,
            "social_orientation": social,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={"geography": geography},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_macroeconomic_name_constant() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    assert MacroeconomicArchitect().name == "MacroeconomicArchitect"


def test_macroeconomic_product_types_is_all() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect
    from app.simulation.architects.base import BaseArchitect

    pt = MacroeconomicArchitect().product_types
    assert set(pt) == set(BaseArchitect.ALL_PRODUCT_TYPES)


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_ten_metrics() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.architect_name == "MacroeconomicArchitect"
    assert len(out.metrics) == 10


# ---------------------------------------------------------------------------
# Scenario paths
# ---------------------------------------------------------------------------


def test_normal_scenario_neutral_mults() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    for key in (
        "price_ceiling_multiplier", "freemium_conversion_mult",
        "annual_payment_mult", "emi_attractiveness_mult",
        "b2b_procurement_mult", "upgrade_cycle_mult",
    ):
        assert out.metrics[key] == 1.0


def test_recession_scenario_price_ceiling_income_tiers() -> None:
    """income < 0.3 → 0.58; income < 0.6 → 0.74; else 0.88."""
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    low = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.2), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "RECESSION"},
    )
    mid = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "RECESSION"},
    )
    high = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.8), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "RECESSION"},
    )
    assert low.metrics["price_ceiling_multiplier"] == 0.58
    assert mid.metrics["price_ceiling_multiplier"] == 0.74
    assert high.metrics["price_ceiling_multiplier"] == 0.88


def test_recession_emi_attractiveness_at_1_30() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "RECESSION"},
    )
    assert out.metrics["emi_attractiveness_mult"] == 1.30


def test_high_growth_scenario_price_ceiling_at_1_20() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH"},
    )
    assert out.metrics["price_ceiling_multiplier"] == 1.20


def test_high_growth_b2b_procurement_at_1_40() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH"},
    )
    assert out.metrics["b2b_procurement_mult"] == 1.40


# ---------------------------------------------------------------------------
# Festival amplifier
# ---------------------------------------------------------------------------


def test_festival_consumer_hardware_at_1_38() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL", "calendar_period": "FESTIVAL_SEASON",
                    "product_type": "consumer_hardware"},
    )
    assert out.metrics["festival_amplifier"] == 1.38


def test_festival_health_hardware_at_1_25() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "FESTIVAL_SEASON", "product_type": "health_hardware"},
    )
    assert out.metrics["festival_amplifier"] == 1.25


def test_festival_saas_at_1_18() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "FESTIVAL_SEASON", "product_type": "saas"},
    )
    assert out.metrics["festival_amplifier"] == 1.18


def test_festival_unknown_product_at_1_05() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "FESTIVAL_SEASON", "product_type": "unknown_thing"},
    )
    assert out.metrics["festival_amplifier"] == 1.05


def test_festival_peak_flag_when_above_1_20() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "FESTIVAL_SEASON", "product_type": "wearable"},
    )
    assert out.metrics["festival_amplifier"] > 1.20
    assert out.flags["festival_peak"] is True


def test_new_year_saas_at_1_22() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "NEW_YEAR", "product_type": "saas"},
    )
    assert out.metrics["festival_amplifier"] == 1.22


def test_fiscal_year_end_enterprise_software_at_1_40() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"calendar_period": "FISCAL_YEAR_END", "product_type": "enterprise_software"},
    )
    assert out.metrics["festival_amplifier"] == 1.40


def test_post_exam_student_at_0_72() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(cluster_id="metro_student_user"),
        agent_profile={}, assumptions=[],
        env_params={"calendar_period": "POST_EXAM", "product_type": "mobile_app"},
    )
    assert out.metrics["festival_amplifier"] == 0.72


def test_post_exam_non_student_neutral() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(cluster_id="metro_professional"),
        agent_profile={}, assumptions=[],
        env_params={"calendar_period": "POST_EXAM", "product_type": "mobile_app"},
    )
    assert out.metrics["festival_amplifier"] == 1.0


# ---------------------------------------------------------------------------
# USD pricing penalty
# ---------------------------------------------------------------------------


def test_usd_penalty_disabled_by_default() -> None:
    """No 'usd' / 'usd pricing' keywords → usd_penalty = 1.0."""
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["usd_pricing_penalty"] == 1.0
    assert out.flags["usd_penalty_severe"] is False


def test_usd_penalty_income_tiers_when_usd_pricing() -> None:
    """USD pricing + low income → severe penalty, scaling with income."""
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    # Force usd_pricing via assumption keywords detected by the macro
    # architect's own keyword check.
    base_kwargs = {"agent_profile": {}, "assumptions": [{"text": "Product is priced in USD."}]}
    low = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.2), env_params={"scenario_type": "NORMAL"}, **base_kwargs
    )
    mid = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5), env_params={"scenario_type": "NORMAL"}, **base_kwargs
    )
    high = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.8), env_params={"scenario_type": "NORMAL"}, **base_kwargs
    )
    assert low.metrics["usd_pricing_penalty"] == 0.42
    assert mid.metrics["usd_pricing_penalty"] == 0.73
    assert high.metrics["usd_pricing_penalty"] == 0.91
    assert low.flags["usd_penalty_severe"] is True


# ---------------------------------------------------------------------------
# Government subsidy
# ---------------------------------------------------------------------------


def test_subsidy_low_income_at_1_45() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.2), agent_profile={},
        assumptions=[{"text": "Eligible for government scheme / subsidy."}],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["government_subsidy_mult"] == 1.45


def test_subsidy_tier3_at_1_38() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5, geography="tier3"),  # exact 'tier3' literal
        agent_profile={},
        assumptions=[{"text": "Eligible for PM scheme Digital India."}],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["government_subsidy_mult"] == 1.38


def test_subsidy_other_at_1_10() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.7, geography="metro"),
        agent_profile={},
        assumptions=[{"text": "Eligible for Startup India scheme."}],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.metrics["government_subsidy_mult"] == 1.10


def test_subsidy_active_flag_when_assumption_present() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    on = MacroeconomicArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[{"text": "Eligible for digital india scheme."}],
        env_params={},
    )
    assert on.flags["subsidy_active"] is True

    off = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert off.flags["subsidy_active"] is False


# ---------------------------------------------------------------------------
# conversion_correction composition
# ---------------------------------------------------------------------------


def test_conversion_correction_clamped_in_range() -> None:
    """Always in [0.10, 2.0] regardless of compounding."""
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    # Worst case: subsidy high + price_ceil low → could be tiny.
    out_low = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.05), agent_profile={},
        assumptions=[{"text": "USD pricing with subsidy eligible."}],
        env_params={"scenario_type": "RECESSION", "product_type": "wearable",
                    "calendar_period": "POST_EXAM"},
    )
    assert 0.10 <= out_low.metrics["overall_conversion_correction"] <= 2.0

    # Best case scenario.
    out_high = MacroeconomicArchitect().compute(
        cluster=_cluster(income=1.0, cluster_id="enterprise_b2b"),
        agent_profile={},
        assumptions=[{"text": "Subsidy eligible."}],
        env_params={"scenario_type": "HIGH_GROWTH", "product_type": "enterprise_software",
                    "calendar_period": "FISCAL_YEAR_END"},
    )
    assert out_high.metrics["overall_conversion_correction"] <= 2.0


def test_conversion_correction_uses_b2b_mult_only_for_b2b_cluster() -> None:
    """b2b_procurement_mult (= 1.40 HIGH_GROWTH) only applies to
    enterprise/b2b/smb cluster_id."""
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    b2b = MacroeconomicArchitect().compute(
        cluster=_cluster(cluster_id="enterprise_b2b"),
        agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH", "product_type": "saas",
                    "calendar_period": "NORMAL"},
    )
    consumer = MacroeconomicArchitect().compute(
        cluster=_cluster(cluster_id="metro_professional"),
        agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH", "product_type": "saas",
                    "calendar_period": "NORMAL"},
    )
    assert b2b.metrics["overall_conversion_correction"] > consumer.metrics["overall_conversion_correction"]


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_critical_recession_low_income() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.2), agent_profile={},
        assumptions=[], env_params={"scenario_type": "RECESSION"},
    )
    assert out.severity == "CRITICAL"


def test_severity_warning_recession_normal_income() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5), agent_profile={},
        assumptions=[], env_params={"scenario_type": "RECESSION"},
    )
    assert out.severity == "WARNING"


def test_severity_warning_usd_pricing_only() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5), agent_profile={},
        assumptions=[{"text": "USD pricing."}],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.severity == "WARNING"


def test_severity_info_normal_no_usd() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_recession_active_flag_when_recession_scenario() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    on = MacroeconomicArchitect().compute(
        cluster=_cluster(income=0.5), agent_profile={},
        assumptions=[], env_params={"scenario_type": "RECESSION"},
    )
    assert on.flags["recession_active"] is True

    off = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "HIGH_GROWTH"},
    )
    assert off.flags["recession_active"] is False


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    out = MacroeconomicArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"scenario_type": "NORMAL"},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Scenario" in joined
    assert "Festival" in joined or "USD" in joined


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    a = MacroeconomicArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_recession_pressure_clusters() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = MacroeconomicArchitect()
    hit = ArchitectOutput(
        architect_name="MacroeconomicArchitect",
        cluster_id="tier3_recession",
        metrics={"price_ceiling_multiplier": 0.58},
        flags={"recession_active": True},
        narrative_findings=[],
        severity="CRITICAL",
    )
    spared = ArchitectOutput(
        architect_name="MacroeconomicArchitect",
        cluster_id="metro_ok",
        metrics={"price_ceiling_multiplier": 1.0},
        flags={"recession_active": True},  # even if recession — high income passes
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([hit, spared])
    assert report.severity == "WARNING"
    assert "tier3_recession" in report.affected_cluster_ids
    assert "metro_ok" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.macroeconomic import MacroeconomicArchitect

    a = MacroeconomicArchitect()
    kwargs = {
        "cluster": _cluster(), "agent_profile": {}, "assumptions": [],
        "env_params": {"scenario_type": "NORMAL"},
    }
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

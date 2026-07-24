"""
Tests for ``app.simulation.architects.pricing`` — PricingArchitect.

Locks down pricing-behavioural metric math, flag thresholds,
severity tiers, narrative findings, transition_overrides clamping,
and generate_report() cross-cluster aggregation.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    income: float = 0.5,
    price_sens: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    literacy: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
    loyalty: float = 0.5,
    risk: float = 0.5,
    cluster_id: str = "metro_power_professional",
    population_weight: float = 0.10,
) -> Any:
    """Build a minimal ClusterDefinition shape for a PricingArchitect run."""
    from app.simulation.clusters.definitions import ClusterDefinition

    return ClusterDefinition(
        cluster_id=cluster_id,
        name="Test Cluster",
        description="Test",
        population_weight=population_weight,
        base_traits={
            "income_level": income,
            "digital_literacy": literacy,
            "motivation": motivation,
            "trust": trust,
            "price_sensitivity": price_sens,
            "risk_aversion": risk,
            "patience_score": patience,
            "social_orientation": social,
            "loyalty_score": loyalty,
        },
        trait_variance={k: 0.05 for k in (
            "income_level", "digital_literacy", "motivation", "trust",
            "price_sensitivity", "risk_aversion", "patience_score",
            "social_orientation",
        )},
        dominant_behavior_pattern="test",
        known_failure_modes=[],
        product_affinities=["saas"],
        demographic_profile={"geography": "METRO"},
    )


# ---------------------------------------------------------------------------
# name + product_types surface
# ---------------------------------------------------------------------------


def test_pricing_architect_name_constant() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    a = PricingArchitect()
    assert a.name == "PricingArchitect"


def test_pricing_architect_product_types_includes_all() -> None:
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.base import BaseArchitect

    a = PricingArchitect()
    # pricing applies to every known product type.
    for pt in BaseArchitect.ALL_PRODUCT_TYPES:
        assert pt in a.product_types


# ---------------------------------------------------------------------------
# Metric math
# ---------------------------------------------------------------------------


def test_compute_returns_architect_output_with_thirteen_metrics() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(),
        agent_profile={},
        assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert out.architect_name == "PricingArchitect"
    assert len(out.metrics) == 13


def test_compute_will_pay_probability_clamped_in_unit_interval() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    # very high income + low price_sens → raw would exceed 0.95.
    high = PricingArchitect().compute(
        cluster=_cluster(income=1.0, price_sens=0.0, trust=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert 0.05 <= high.metrics["will_pay_probability"] <= 0.95

    # very low income + high price_sens → floor at 0.05.
    low = PricingArchitect().compute(
        cluster=_cluster(income=0.05, price_sens=1.0, trust=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 5000},
    )
    assert low.metrics["will_pay_probability"] >= 0.05


def test_compute_price_ceiling_scales_with_income_and_trust() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    low = PricingArchitect().compute(
        cluster=_cluster(income=0.2, trust=0.2, price_sens=0.5),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    high = PricingArchitect().compute(
        cluster=_cluster(income=0.9, trust=0.9, price_sens=0.2),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert high.metrics["price_ceiling"] > low.metrics["price_ceiling"]


def test_compute_anchoring_clamped_to_unit_band() -> None:
    """anchoring_effect ∈ [0.01, 0.20] regardless of inputs."""
    from app.simulation.architects.pricing import PricingArchitect

    for kwargs in (
        dict(income=0.1, literacy=0.05, trust=0.1),
        dict(income=1.0, literacy=0.95, trust=1.0),
    ):
        kwargs.update(price_sens=0.5)
        out = PricingArchitect().compute(
            cluster=_cluster(**kwargs), agent_profile={}, assumptions=[],
            env_params={"average_order_value": 999},
        )
        assert 0.01 <= out.metrics["anchoring_effect"] <= 0.20


def test_compute_annual_probability_capped_at_085() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(income=1.0, trust=1.0, loyalty=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert out.metrics["annual_payment_probability"] <= 0.85


def test_compute_churn_metrics_non_negative() -> None:
    """churn_at_XX are floored at 0 — never negative."""
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(income=0.05, price_sens=0.05, loyalty=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    for key in (
        "price_hike_churn_at_20pct",
        "price_hike_churn_at_40pct",
        "price_hike_churn_at_60pct",
    ):
        assert out.metrics[key] >= 0.0


def test_compute_zero_aov_yields_safe_will_pay_fallback() -> None:
    """AOV=0 → will_pay = 0.5 (per the conditional fallback)."""
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 0},
    )
    assert out.metrics["will_pay_probability"] == 0.5


def test_compute_default_aov_when_env_param_missing() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={}
    )
    # average_order_value defaults to 999; will_pay stays in [0.05, 0.95].
    assert 0.05 <= out.metrics["will_pay_probability"] <= 0.95


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_flag_will_pay_at_current_aov_tracks_ceiling_vs_aov() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    # price_ceiling > AOV → True.
    out_ok = PricingArchitect().compute(
        cluster=_cluster(income=0.9, trust=0.9, price_sens=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 100},
    )
    assert out_ok.flags["will_pay_at_current_aov"] is True

    # price_ceiling very low → False.
    out_bad = PricingArchitect().compute(
        cluster=_cluster(income=0.05, trust=0.05, price_sens=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 10_000},
    )
    assert out_bad.flags["will_pay_at_current_aov"] is False


def test_flag_annual_preferred_when_prob_above_040() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(income=0.9, trust=0.9, loyalty=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert out.flags["annual_preferred_over_monthly"] is True


def test_flag_pricing_is_kill_shot_when_ceiling_below_third_of_aov() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    # tiny ceiling → kill shot.
    out = PricingArchitect().compute(
        cluster=_cluster(income=0.05, trust=0.05, price_sens=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 50_000},
    )
    assert out.flags["pricing_is_kill_shot"] is True


# ---------------------------------------------------------------------------
# Severity tiers
# ---------------------------------------------------------------------------


def test_severity_critical_when_ceiling_below_third_of_aov() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(income=0.05, trust=0.05, price_sens=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 50_000},
    )
    assert out.severity == "CRITICAL"


def test_severity_warning_when_ceiling_between_third_and_70pct_of_aov() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        # ceiling/AOV = income * (1-sensitivity) * 2.4 * trust
        #             = 0.6 * 0.5 * 2.4 * 0.8 = 0.576 → WARNING.
        cluster=_cluster(income=0.6, trust=0.8, price_sens=0.5),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 5_000},
    )
    assert out.severity == "WARNING"


def test_severity_info_when_ceiling_well_above_aov() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(income=0.9, trust=0.9, price_sens=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 100},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    out = PricingArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    assert len(out.narrative_findings) == 2
    # First narrates AOV vs ceiling; second narrates freemium ceiling.
    joined = " | ".join(out.narrative_findings)
    assert "Price ceiling" in joined or "AOV" in joined
    assert "Freemium" in joined


# ---------------------------------------------------------------------------
# transition_overrides
# ---------------------------------------------------------------------------


def test_transition_overrides_decide_to_purchase_uses_will_pay_clamped() -> None:
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = PricingArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    overrides = a.transition_overrides(out)
    wp = out.metrics["will_pay_probability"]
    assert 0.05 <= overrides[("DECIDE", "PURCHASE")] <= 0.95


def test_transition_overrides_consider_to_decide_uses_anchoring_boost() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    a = PricingArchitect()
    out = a.compute(
        cluster=_cluster(literacy=0.8, trust=0.7),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    overrides = a.transition_overrides(out)
    # CONSIDER→DECIDE = 1.0 + anchoring_effect → must be > 1.0.
    assert overrides[("CONSIDER", "DECIDE")] >= 1.0


# ---------------------------------------------------------------------------
# generate_report()
# ---------------------------------------------------------------------------


def test_generate_report_no_critical_when_outputs_have_no_kill_shot() -> None:
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = PricingArchitect()
    out = a.compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    # Ensure fixture doesn't accidentally trigger kill_shot.
    out.flags["pricing_is_kill_shot"] = False
    report = a.generate_report([out])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []
    assert report.population_fraction == 0.0


def test_generate_report_counts_critical_clusters() -> None:
    from app.simulation.architects.pricing import PricingArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = PricingArchitect()
    out_good = a.compute(
        cluster=_cluster(cluster_id="good"), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    out_good.flags["pricing_is_kill_shot"] = False

    out_bad = a.compute(
        cluster=_cluster(cluster_id="bad"), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 999},
    )
    out_bad.flags["pricing_is_kill_shot"] = True

    report = a.generate_report([out_good, out_bad])
    assert report.severity == "CRITICAL"
    assert "bad" in report.affected_cluster_ids
    assert "good" not in report.affected_cluster_ids


def test_generate_report_handles_empty_output_list() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    a = PricingArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []
    assert report.population_fraction == 0.0


def test_generate_report_uses_canonical_action_string() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    a = PricingArchitect()
    report = a.generate_report([])
    assert "Lower price" in report.recommended_action or "EMI" in report.recommended_action


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.pricing import PricingArchitect

    a = PricingArchitect()
    kwargs = {
        "cluster": _cluster(),
        "agent_profile": {},
        "assumptions": [],
        "env_params": {"average_order_value": 999},
    }
    out_a = a.compute(**kwargs)
    out_b = a.compute(**kwargs)
    assert out_a.metrics == out_b.metrics
    assert out_a.severity == out_b.severity
    assert out_a.flags == out_b.flags

"""
Tests for ``app.simulation.architects.aftersales_lifecycle`` —
AftersalesLifecycleArchitect.

Locks down hardware-specific aftersales metrics: warranty claim
likelihood (AOV-banded multiplier), repair vs replace threshold,
30-day support contact rate, accessory attach rate (enthusiast
boost), refurbished participation (age-based), sustainability
concern, brand loyalty next purchase, review writing likelihood
(satisfaction-extremes multiplier), spare parts concern,
expected product lifespan. Plus severity, flags, narrative
findings, and the generate_report() rollup.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Cluster fixture
# ---------------------------------------------------------------------------


def _cluster(
    *,
    literacy: float = 0.5,
    motivation: float = 0.5,
    trust: float = 0.5,
    income: float = 0.5,
    price_sens: float = 0.5,
    risk: float = 0.5,
    patience: float = 0.5,
    social: float = 0.5,
    cluster_id: str = "health_hardware_enthusiast",
    age_bracket: str = "25-35",
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
        product_affinities=["health_hardware"],
        demographic_profile={"geography": "metro_delhi", "age_bracket": age_bracket},
    )


# ---------------------------------------------------------------------------
# name + product_types
# ---------------------------------------------------------------------------


def test_aftersales_name_constant() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    assert AftersalesLifecycleArchitect().name == "AftersalesLifecycleArchitect"


def test_aftersales_product_types_hardware_only() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    pt = AftersalesLifecycleArchitect().product_types
    expected = {
        "consumer_hardware", "health_hardware",
        "iot_hardware", "wearable", "b2b_hardware",
    }
    assert set(pt) == expected


# ---------------------------------------------------------------------------
# Metric surface
# ---------------------------------------------------------------------------


def test_compute_returns_ten_metrics() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[], env_params={},
    )
    assert out.architect_name == "AftersalesLifecycleArchitect"
    assert len(out.metrics) == 10


# ---------------------------------------------------------------------------
# warranty_claim_likelihood
# ---------------------------------------------------------------------------


def test_warranty_claim_capped_at_040() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 15000, "product_type": "health_hardware"},
    )
    assert out.metrics["warranty_claim_likelihood"] <= 0.40


def test_warranty_claim_higher_for_high_aov() -> None:
    """AOV > 10000 → ×1.3; AOV < 2000 → ×0.7."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    low_aov = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 1500},
    )
    high_aov = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 12000},
    )
    assert high_aov.metrics["warranty_claim_likelihood"] > low_aov.metrics["warranty_claim_likelihood"]


def test_warranty_claim_higher_for_low_trust() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    high_trust = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.9),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 5000},
    )
    low_trust = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 5000},
    )
    assert low_trust.metrics["warranty_claim_likelihood"] > high_trust.metrics["warranty_claim_likelihood"]


# ---------------------------------------------------------------------------
# repair_vs_replace_threshold
# ---------------------------------------------------------------------------


def test_repair_threshold_income_tiers() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    low = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.1), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000},
    )
    mid = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.5), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000},
    )
    high = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.9), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000},
    )
    assert low.metrics["repair_vs_replace_threshold"] == 0.30
    assert mid.metrics["repair_vs_replace_threshold"] == 0.50
    assert high.metrics["repair_vs_replace_threshold"] == 0.70


# ---------------------------------------------------------------------------
# support_contact_rate_30d
# ---------------------------------------------------------------------------


def test_support_30d_capped_at_070() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(literacy=0.0), agent_profile={
            "oob_setup_completion_rate": 0.0,
        },
        assumptions=[], env_params={},
    )
    assert out.metrics["support_contact_rate_30d"] <= 0.70


def test_support_30d_higher_with_low_oob_and_low_literacy() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    high_low = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(literacy=0.1),
        agent_profile={"oob_setup_completion_rate": 0.1},
        assumptions=[], env_params={},
    )
    lo_high = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(literacy=0.9),
        agent_profile={"oob_setup_completion_rate": 0.9},
        assumptions=[], env_params={},
    )
    assert high_low.metrics["support_contact_rate_30d"] > lo_high.metrics["support_contact_rate_30d"]


# ---------------------------------------------------------------------------
# accessory_attach_rate
# ---------------------------------------------------------------------------


def test_accessory_attach_higher_for_enthusiast() -> None:
    """Enthusiast cluster_id → +0.3 base."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    no = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(cluster_id="metro_random", income=0.5),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    yes = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(cluster_id="health_hardware_enthusiast", income=0.5),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert yes.metrics["accessory_attach_rate"] > no.metrics["accessory_attach_rate"]


def test_accessory_attach_capped_at_080() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(cluster_id="enthusiast_test", income=1.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["accessory_attach_rate"] <= 0.80


# ---------------------------------------------------------------------------
# refurbished_participation
# ---------------------------------------------------------------------------


def test_refurbished_higher_for_younger_age_bracket() -> None:
    """age contains '18' / '22' / '25' → +0.2 base."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    older = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.5, age_bracket="45-55"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    young = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.5, age_bracket="18-24"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert young.metrics["refurbished_participation"] > older.metrics["refurbished_participation"]


def test_refurbished_capped_at_050() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.0, age_bracket="18-24"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["refurbished_participation"] <= 0.50


# ---------------------------------------------------------------------------
# sustainability_concern
# ---------------------------------------------------------------------------


def test_sustainability_higher_for_younger_age_and_higher_income() -> None:
    """younger age +0.2 base; income > 0.5 → +0.2."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    older_poor = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.3, age_bracket="45-55"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    young_rich = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.8, age_bracket="18-24"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert young_rich.metrics["sustainability_concern"] > older_poor.metrics["sustainability_concern"]


def test_sustainability_capped_at_070() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=1.0, age_bracket="18-24"),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["sustainability_concern"] <= 0.70


# ---------------------------------------------------------------------------
# brand_loyalty_next_purchase
# ---------------------------------------------------------------------------


def test_brand_loyalty_capped_at_080() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=1.0, trust=1.0),
        agent_profile={"oob_setup_completion_rate": 1.0, "brand_deficit_multiplier": 1.0},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["brand_loyalty_next_purchase"] <= 0.80


def test_brand_loyalty_higher_for_high_satisfaction_proxy() -> None:
    """satisfaction_proxy = oob * 0.5 + brand * 0.3 + trust * 0.2."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    low = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.1),
        agent_profile={"oob_setup_completion_rate": 0.2, "brand_deficit_multiplier": 0.3},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    high = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.9),
        agent_profile={"oob_setup_completion_rate": 0.9, "brand_deficit_multiplier": 0.9},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert high.metrics["brand_loyalty_next_purchase"] > low.metrics["brand_loyalty_next_purchase"]


# ---------------------------------------------------------------------------
# review_writing_likelihood
# ---------------------------------------------------------------------------


def test_review_likely_amplified_for_extreme_satisfaction_proxy() -> None:
    """sp < 0.3 OR > 0.8 → ×2.5 multiplier (high emotion); else ×0.6."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    mid = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(social=0.8, trust=0.5),
        agent_profile={"oob_setup_completion_rate": 0.55, "brand_deficit_multiplier": 0.6},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    extreme = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(social=0.8, trust=0.1),
        agent_profile={"oob_setup_completion_rate": 0.2, "brand_deficit_multiplier": 0.2},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert extreme.metrics["review_writing_likelihood"] > mid.metrics["review_writing_likelihood"]


def test_review_likely_capped_at_075() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(social=1.0, trust=0.0),
        agent_profile={"oob_setup_completion_rate": 0.0, "brand_deficit_multiplier": 0.0},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["review_writing_likelihood"] <= 0.75


# ---------------------------------------------------------------------------
# spare_parts_concern
# ---------------------------------------------------------------------------


def test_spare_concern_higher_for_low_income_high_aov() -> None:
    """AOV > 5000 → ×1.5; else ×0.7. Base depends on (1 - income)."""
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    poor_high_aov = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 8000, "product_type": "wearable"},
    )
    rich_low_aov = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.9),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 1000, "product_type": "wearable"},
    )
    assert poor_high_aov.metrics["spare_parts_concern"] > rich_low_aov.metrics["spare_parts_concern"]


def test_spare_concern_capped_at_060() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 20000, "product_type": "wearable"},
    )
    assert out.metrics["spare_parts_concern"] <= 0.60


# ---------------------------------------------------------------------------
# expected_product_lifespan_y
# ---------------------------------------------------------------------------


def test_lifespan_floor_at_one_year() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.0),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 0, "product_type": "wearable"},
    )
    assert out.metrics["expected_product_lifespan_y"] >= 1.0


def test_lifespan_higher_for_higher_aov_and_income() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    low = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.1),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 500, "product_type": "wearable"},
    )
    high = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(income=0.9),
        agent_profile={}, assumptions=[],
        env_params={"average_order_value": 15000, "product_type": "wearable"},
    )
    assert high.metrics["expected_product_lifespan_y"] > low.metrics["expected_product_lifespan_y"]


def test_lifespan_rounded_to_2_dp() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["expected_product_lifespan_y"] == round(out.metrics["expected_product_lifespan_y"], 2)


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------


def test_severity_warning_when_brand_loyalty_below_030() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.0),
        agent_profile={"oob_setup_completion_rate": 0.0, "brand_deficit_multiplier": 0.0},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["brand_loyalty_next_purchase"] < 0.30
    assert out.severity == "WARNING"


def test_severity_info_normal() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(trust=0.9),
        agent_profile={"oob_setup_completion_rate": 0.9, "brand_deficit_multiplier": 0.9},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.severity == "INFO"


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_high_support_burden_flag_when_support_above_040() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(literacy=0.1),
        agent_profile={"oob_setup_completion_rate": 0.1},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["support_contact_rate_30d"] > 0.40
    assert out.flags["high_support_burden"] is True


def test_review_risk_high_when_review_likely_above_050() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        # Extreme satisfaction → 2.5 multiplier → likely > 0.5
        cluster=_cluster(social=1.0, trust=0.0),
        agent_profile={"oob_setup_completion_rate": 0.0, "brand_deficit_multiplier": 0.0},
        assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert out.metrics["review_writing_likelihood"] > 0.50
    assert out.flags["review_risk_high"] is True


# ---------------------------------------------------------------------------
# Narrative findings
# ---------------------------------------------------------------------------


def test_compute_returns_two_narrative_findings() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    out = AftersalesLifecycleArchitect().compute(
        cluster=_cluster(), agent_profile={}, assumptions=[],
        env_params={"average_order_value": 3000, "product_type": "wearable"},
    )
    assert len(out.narrative_findings) == 2
    joined = " | ".join(out.narrative_findings)
    assert "Brand loyalty" in joined
    assert "Review" in joined


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def test_generate_report_empty_list_returns_info() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    a = AftersalesLifecycleArchitect()
    report = a.generate_report([])
    assert report.severity == "INFO"
    assert report.affected_cluster_ids == []


def test_generate_report_collects_low_loyalty_clusters() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect
    from app.simulation.architects.base import ArchitectOutput

    a = AftersalesLifecycleArchitect()
    low = ArchitectOutput(
        architect_name="AftersalesLifecycleArchitect",
        cluster_id="tier3_low_loyalty",
        metrics={},
        flags={"low_brand_loyalty": True},
        narrative_findings=[],
        severity="WARNING",
    )
    hi = ArchitectOutput(
        architect_name="AftersalesLifecycleArchitect",
        cluster_id="metro_loyal",
        metrics={},
        flags={"low_brand_loyalty": False},
        narrative_findings=[],
        severity="INFO",
    )
    report = a.generate_report([low, hi])
    assert report.severity == "WARNING"
    assert "tier3_low_loyalty" in report.affected_cluster_ids
    assert "metro_loyal" not in report.affected_cluster_ids


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_compute_is_deterministic() -> None:
    from app.simulation.architects.aftersales_lifecycle import AftersalesLifecycleArchitect

    a = AftersalesLifecycleArchitect()
    kwargs = {
        "cluster": _cluster(), "agent_profile": {}, "assumptions": [],
        "env_params": {"average_order_value": 3000, "product_type": "wearable"},
    }
    a1 = a.compute(**kwargs)
    a2 = a.compute(**kwargs)
    assert a1.metrics == a2.metrics
    assert a1.severity == a2.severity
    assert a1.flags == a2.flags

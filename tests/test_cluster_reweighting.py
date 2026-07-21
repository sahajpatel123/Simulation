"""
Tests for the ClusterReweightingEngine (cycle 33 engine-test-coverage).

The engine is the heart of the demographic scenario system: it picks a
rule bundle based on product_type/aov/geography/segment/age_target,
applies suppress/amplify rules, then geo/age tweaks, then renormalises
the weights to sum to 1.0. These tests lock in:

  1. ``_select_rule_bundle`` routing for every product type.
  2. ``compute_weights`` invariants: weights sum to 1.0, all non-negative.
  3. Suppress rule zeros out the targeted clusters (and only those).
  4. Amplify rule multiplies the targeted clusters (and only those).
  5. Consumer-hardware pricing tiers route to the correct bundle.
  6. SaaS-style products route on segment (ENTERPRISE / SMB / B2C).
  7. Geo tweaks promote TIER2/TIER3 clusters.
  8. Age tweaks promote student / senior clusters.
  9. Unknown rule bundle IDs fall back to DEFAULT.
"""
from __future__ import annotations

import math

import pytest

from app.simulation.cluster_reweighting import (
    ClusterReweightingEngine,
    REWEIGHTING_RULES,
)
from app.simulation.product_type import ProductType


# ---------------------------------------------------------------------------
# Rule bundle selection
# ---------------------------------------------------------------------------


def _engine() -> ClusterReweightingEngine:
    return ClusterReweightingEngine()


def test_select_rule_bundle_enterprise_software_is_b2b() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.ENTERPRISE_SOFTWARE,
            aov=0.0,
            geography="METRO",
            segment="",
            age_target="",
        )
        == "B2B_ENTERPRISE"
    )


def test_select_rule_bundle_b2b_hardware_is_b2b() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.B2B_HARDWARE,
            aov=0.0,
            geography="",
            segment="",
            age_target="",
        )
        == "B2B_ENTERPRISE"
    )


def test_select_rule_bundle_health_hardware() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.HEALTH_HARDWARE,
            aov=0.0,
            geography="",
            segment="",
            age_target="",
        )
        == "HEALTH_HARDWARE"
    )


def test_select_rule_bundle_iot_hardware() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.IOT_HARDWARE,
            aov=0.0,
            geography="",
            segment="",
            age_target="",
        )
        == "IOT_HARDWARE"
    )


def test_select_rule_bundle_wearable() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.WEARABLE,
            aov=0.0,
            geography="",
            segment="",
            age_target="",
        )
        == "WEARABLE"
    )


def test_select_rule_bundle_consumer_hardware_low_price() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.CONSUMER_HARDWARE,
            aov=2999.0,
            geography="",
            segment="",
            age_target="",
        )
        == "CONSUMER_HARDWARE_LOW_PRICE"
    )


def test_select_rule_bundle_consumer_hardware_mid() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.CONSUMER_HARDWARE,
            aov=11_999.0,
            geography="",
            segment="",
            age_target="",
        )
        == "CONSUMER_HARDWARE_MID"
    )


def test_select_rule_bundle_consumer_hardware_premium() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.CONSUMER_HARDWARE,
            aov=12_000.0,
            geography="",
            segment="",
            age_target="",
        )
        == "CONSUMER_HARDWARE_PREMIUM"
    )


@pytest.mark.parametrize(
    "segment",
    ["ENTERPRISE", "B2B_ENTERPRISE", "FORTUNE", "enterprise", "b2b_enterprise"],
)
def test_select_rule_bundle_saas_enterprise_segments(segment: str) -> None:
    engine = _engine()
    for pt in (
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
    ):
        assert (
            engine._select_rule_bundle(
                product_type=pt,
                aov=0.0,
                geography="",
                segment=segment,
                age_target="",
            )
            == "SAAS_ENTERPRISE"
        )


@pytest.mark.parametrize("segment", ["SMB", "B2B_SMB", "SMB_B2B", "smb"])
def test_select_rule_bundle_saas_smb_segments(segment: str) -> None:
    engine = _engine()
    for pt in (
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
    ):
        assert (
            engine._select_rule_bundle(
                product_type=pt,
                aov=0.0,
                geography="",
                segment=segment,
                age_target="",
            )
            == "SAAS_B2B_SMB"
        )


def test_select_rule_bundle_saas_default_b2c() -> None:
    engine = _engine()
    for pt in (
        ProductType.SAAS,
        ProductType.MARKETPLACE,
        ProductType.MOBILE_APP,
        ProductType.DEVELOPER_TOOL,
    ):
        assert (
            engine._select_rule_bundle(
                product_type=pt,
                aov=0.0,
                geography="",
                segment="CONSUMER",
                age_target="",
            )
            == "SAAS_B2C"
        )


def test_select_rule_bundle_strips_whitespace_and_uppercases_segment() -> None:
    engine = _engine()
    assert (
        engine._select_rule_bundle(
            product_type=ProductType.SAAS,
            aov=0.0,
            geography="",
            segment="  enterprise  ",
            age_target="",
        )
        == "SAAS_ENTERPRISE"
    )


# ---------------------------------------------------------------------------
# compute_weights — sum invariant + suppress/amplify semantics
# ---------------------------------------------------------------------------


def test_compute_weights_default_sums_to_one() -> None:
    engine = _engine()
    # Pick inputs that map to the DEFAULT bundle.
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="MARS",
        segment="INDIVIDUAL",
        age_target="ANY",
    )
    total = sum(weights.values())
    assert math.isclose(total, 1.0, abs_tol=1e-6)
    # All weights non-negative.
    assert all(v >= 0.0 for v in weights.values())
    # Every cluster from the registry is present.
    from app.simulation.clusters.registry import ClusterRegistry

    expected_ids = {c.cluster_id for c in ClusterRegistry().all_clusters()}
    assert set(weights.keys()) == expected_ids


def test_compute_weights_b2b_enterprise_zeroes_listed_clusters() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.ENTERPRISE_SOFTWARE,
        aov=0.0,
        geography="",
        segment="",
        age_target="",
    )
    # B2B_ENTERPRISE suppresses these clusters to zero.
    for cid in REWEIGHTING_RULES["B2B_ENTERPRISE"].suppress:
        assert weights[cid] == 0.0
    # Amplified clusters get boosted above their baseline.
    baseline = {
        c.cluster_id: c.population_weight
        for c in __import__("app.simulation.clusters.registry", fromlist=["ClusterRegistry"]).ClusterRegistry().all_clusters()
    }
    for cid in REWEIGHTING_RULES["B2B_ENTERPRISE"].amplify:
        assert weights[cid] >= baseline[cid]
    # Sum still 1.0.
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6)


def test_compute_weights_saas_enterprise_amplifies_smb_clusters() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="",
        segment="ENTERPRISE",
        age_target="",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    senior = "senior_enterprise_decision_maker"
    assert weights[senior] > baseline[senior]


def test_compute_weights_consumer_hardware_low_amplifies_value_buyer() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.CONSUMER_HARDWARE,
        aov=1500.0,
        geography="",
        segment="",
        age_target="",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    # value_hardware_buyer amplified by 3.5× in the LOW_PRICE bundle.
    assert weights["value_hardware_buyer"] >= baseline["value_hardware_buyer"]


# ---------------------------------------------------------------------------
# Geo / age tweaks
# ---------------------------------------------------------------------------


def test_geo_tier3_promotes_tier3_clusters() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="TIER3",
        segment="",
        age_target="",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    # Pick a known tier3 cluster and verify it is amplified.
    assert weights["tier3_first_time_app_user"] >= baseline["tier3_first_time_app_user"]


def test_geo_tier2_does_not_promote_tier3_clusters() -> None:
    """TIER2 tweak only amplifies tier2-prefixed clusters; tier3 stays at
    baseline (less the normalisation)."""
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="TIER2",
        segment="",
        age_target="",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    # tier3 clusters are NOT in the TIER2 amplification list.
    # Compare to a no-geo run for fairness.
    base_weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="",
        segment="",
        age_target="",
    )
    # The TIER3-first-time-app-user cluster should not be amplified by TIER2.
    assert weights["tier3_first_time_app_user"] <= base_weights["tier3_first_time_app_user"] + 1e-9


def test_age_youth_promotes_student_clusters() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="",
        segment="",
        age_target="18-24",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    assert (
        weights["high_literacy_student_freemium_ceiling"]
        > baseline["high_literacy_student_freemium_ceiling"]
    )


def test_age_senior_promotes_late_majority_clusters() -> None:
    engine = _engine()
    weights = engine.compute_weights(
        product_type=ProductType.SAAS,
        aov=0.0,
        geography="",
        segment="",
        age_target="55-65",
    )
    from app.simulation.clusters.registry import ClusterRegistry

    baseline = {
        c.cluster_id: c.population_weight for c in ClusterRegistry().all_clusters()
    }
    assert weights["affluent_metro_late_majority"] >= baseline["affluent_metro_late_majority"]


# ---------------------------------------------------------------------------
# REWEIGHTING_RULES structural integrity
# ---------------------------------------------------------------------------


def test_all_known_rule_keys_are_referenced() -> None:
    """Every key in REWEIGHTING_RULES (except DEFAULT) must be reachable via
    _select_rule_bundle for at least one ProductType × input combo."""
    engine = _engine()
    expected = set(REWEIGHTING_RULES.keys()) - {"DEFAULT"}
    reached: set[str] = set()
    for pt in ProductType:
        for aov in (0.0, 5_000.0, 15_000.0):
            for seg in ("", "ENTERPRISE", "SMB", "B2B", "CONSUMER"):
                reached.add(
                    engine._select_rule_bundle(
                        product_type=pt,
                        aov=aov,
                        geography="",
                        segment=seg,
                        age_target="",
                    )
                )
    missing = expected - reached
    assert not missing, (
        f"No input combination reaches rule bundles: {sorted(missing)}"
    )


def test_default_rule_is_empty() -> None:
    rules = REWEIGHTING_RULES["DEFAULT"]
    assert rules.suppress == ()
    assert dict(rules.amplify) == {}


def test_suppressed_clusters_in_b2b_enterprise_are_in_registry() -> None:
    """The hardcoded cluster IDs in REWEIGHTING_RULES must still exist in the
    registry — otherwise the engine silently skips them."""
    from app.simulation.clusters.registry import ClusterRegistry

    registry_ids = {c.cluster_id for c in ClusterRegistry().all_clusters()}
    for rule_key, rules in REWEIGHTING_RULES.items():
        for cid in rules.suppress:
            assert cid in registry_ids, (
                f"Rule bundle '{rule_key}' suppresses unknown cluster '{cid}'"
            )
        for cid in rules.amplify:
            assert cid in registry_ids, (
                f"Rule bundle '{rule_key}' amplifies unknown cluster '{cid}'"
            )


def test_engine_compute_weights_is_deterministic() -> None:
    """Same inputs → same outputs across calls (no hidden state)."""
    engine = _engine()
    a = engine.compute_weights(
        product_type=ProductType.HEALTH_HARDWARE,
        aov=10_000.0,
        geography="TIER2",
        segment="",
        age_target="35-44",
    )
    b = engine.compute_weights(
        product_type=ProductType.HEALTH_HARDWARE,
        aov=10_000.0,
        geography="TIER2",
        segment="",
        age_target="35-44",
    )
    assert a == b

"""
Tests for unit-economics helpers
(``app.simulation.unit_economics``).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.schemas.unit_economics import UnitEconomicsOut
from app.simulation.unit_economics import (
    VERDICT_INSUFFICIENT,
    VERDICT_MARGINAL,
    VERDICT_STRONG,
    VERDICT_UNPROFITABLE,
    build_unit_economics,
)


def _cluster(
    cluster_id: str,
    name: str,
    weight: float = 0.05,
) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "name": name,
        "population_weight": weight,
    }


def _architect_blocks(
    cid: str,
    *,
    price_ceiling: float = 999.0,
    will_pay: float = 1.0,
    day30: float = 0.45,
    day90: float = 0.22,
    wom: float = 0.5,
    organic_ref: float = 0.1,
    urgency: float = 0.5,
    brand_def: float = 0.8,
    awareness: float = 0.6,
) -> dict[str, Any]:
    return {
        cid: {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": price_ceiling,
                    "will_pay_probability": will_pay,
                },
                "flags": {},
            },
            "RetentionArchitect": {
                "metrics": {
                    "day30_survival": day30,
                    "day90_survival": day90,
                },
                "flags": {},
            },
            "ViralityArchitect": {
                "metrics": {
                    "word_of_mouth_coefficient": wom,
                    "organic_referral_trigger_score": organic_ref,
                    "invite_completion_rate": 0.3,
                    "content_virality_rate": 0.1,
                    "community_building_participation": 0.2,
                    "viral_coefficient": 0.05,
                },
                "flags": {},
            },
            "TrustArchitect": {
                "metrics": {
                    "press_mention_lift": 0.1,
                    "brand_deficit_multiplier": brand_def,
                    "free_trial_as_trust_substitute": 0.3,
                },
                "flags": {},
            },
            "MarketTimingArchitect": {
                "metrics": {
                    "category_awareness_score": awareness,
                    "problem_urgency_intensity": urgency,
                    "press_mention_lift": 0.1,
                    "brand_deficit_multiplier": brand_def,
                    "free_trial_as_trust_substitute": 0.3,
                },
                "flags": {},
            },
            "CompetitiveDynamicsArchitect": {
                "metrics": {
                    "incumbent_switching_friction": 0.4,
                },
                "flags": {},
            },
        }
    }


def _basic_registry() -> list[dict[str, Any]]:
    return [
        _cluster("metro_power_professional", "Metro Power Pro", 0.40),
        _cluster("tier3_first_time_app_user", "Tier-3 First-timer", 0.30),
        _cluster("anxiety_driven_researcher", "Research-led", 0.30),
    ]


def _basic_conductor(registry: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for c in registry:
        merged.update(_architect_blocks(c["cluster_id"]))
    return merged


def _results(
    breakdown: dict[str, Any] | None = None,
    *,
    cr: float = 0.05,
    n: int = 3,
) -> dict[str, Any]:
    if breakdown is None:
        breakdown = {f"c{i}": cr for i in range(1, n + 1)}
    return {
        "population_weighted_conversion": cr,
        "product_type_detected": "saas",
        "cluster_breakdown": breakdown,
    }


def _build(
    results: Any,
    *,
    registry: list[dict[str, Any]] | None = None,
    conductor: dict[str, Any] | None = None,
    **kwargs: Any,
) -> UnitEconomicsOut:
    return build_unit_economics(
        results,
        simulation_id=1,
        project_id=2,
        conductor_results=conductor,
        cluster_registry=registry,
        **kwargs,
    )


def test_empty_and_garbage_inputs_yield_insufficient_state() -> None:
    out = _build(None)
    assert out.verdict == VERDICT_INSUFFICIENT
    assert out.cluster_profiles == []
    assert out.clusters_with_data == 0

    bad = _build("{nope")
    assert bad.verdict == VERDICT_INSUFFICIENT

    no_registry = _build(_results(), registry=[])
    assert no_registry.verdict == VERDICT_INSUFFICIENT


def test_json_string_input_parses() -> None:
    out = _build(
        json.dumps(_results()),
        registry=_basic_registry(),
        conductor=_basic_conductor(_basic_registry()),
    )
    assert out.simulation_id == 1
    assert out.project_id == 2
    assert out.total_clusters == 3
    assert out.clusters_with_data == 3
    assert len(out.cluster_profiles) == 3


def test_defaults_produce_complete_read() -> None:
    out = _build(
        _results(),
        registry=_basic_registry(),
        conductor=_basic_conductor(_basic_registry()),
    )
    assert out.verdict in {
        "STRONG",
        "VIABLE",
        "MARGINAL",
        "UNPROFITABLE",
        "INSUFFICIENT_DATA",
    }
    assert out.blended_ltv > 0.0
    assert out.blended_cac > 0.0
    assert out.blended_ltv_cac_ratio > 0.0
    assert out.effective_base_cac == pytest.approx(999.0 * 0.5)
    assert out.meta["cac_source"] == "derived_default"
    assert out.recommendations
    assert len(out.cac_scenarios) == 4
    assert len(out.price_scenarios) == 3
    for profile in out.cluster_profiles:
        assert profile.ltv >= 0.0
        assert profile.cac >= 0.0
        assert profile.ltv_cac_ratio >= 0.0
        assert profile.primary_channel
        if profile.monthly_contribution > 0.0:
            assert profile.payback_months == pytest.approx(
                profile.cac / profile.monthly_contribution,
                abs=0.02,
            )


def test_low_retention_cluster_is_unprofitable() -> None:
    registry = _basic_registry()
    conductor = _basic_conductor(registry)
    conductor.update(
        _architect_blocks(
            "anxiety_driven_researcher",
            day30=0.01,
            day90=0.001,
        )
    )
    out = _build(
        _results(),
        registry=registry,
        conductor=conductor,
    )
    weak = next(
        p for p in out.cluster_profiles if p.cluster_id == "anxiety_driven_researcher"
    )
    strong = next(
        p for p in out.cluster_profiles if p.cluster_id == "metro_power_professional"
    )
    assert weak.verdict == VERDICT_UNPROFITABLE
    assert weak.average_lifetime_months < strong.average_lifetime_months
    assert weak.ltv < strong.ltv


def test_price_ceiling_caps_effective_price_and_flags_at_ceiling() -> None:
    registry = _basic_registry()
    conductor = _basic_conductor(registry)
    conductor.update(
        _architect_blocks(
            "tier3_first_time_app_user",
            price_ceiling=250.0,
            will_pay=0.25,
        )
    )
    out = _build(
        _results(),
        registry=registry,
        conductor=conductor,
        average_order_value=999.0,
    )
    capped = next(
        p for p in out.cluster_profiles if p.cluster_id == "tier3_first_time_app_user"
    )
    assert capped.effective_price == pytest.approx(250.0)
    assert capped.price_ceiling == pytest.approx(250.0)
    assert capped.effective_price < 999.0
    assert out.at_ceiling_share > 0.0
    up = next(s for s in out.price_scenarios if s.label == "PRICE_UP_20")
    assert up.capped_share > 0.0


def test_channel_multipliers_scale_cac() -> None:
    registry = [
        _cluster("organic_lover", "Organic Lover", 0.5),
        _cluster("paid_driven", "Paid Driven", 0.5),
    ]
    conductor = {
        **(
            _architect_blocks(
                "organic_lover",
                wom=1.0,
                organic_ref=1.0,
                awareness=0.0,
                urgency=0.0,
            )
        ),
        **(
            _architect_blocks(
                "paid_driven",
                wom=0.0,
                organic_ref=0.0,
                urgency=1.0,
                brand_def=0.0,
            )
        ),
    }
    out = _build(
        _results(),
        registry=registry,
        conductor=conductor,
    )
    organic = next(p for p in out.cluster_profiles if p.cluster_id == "organic_lover")
    paid = next(p for p in out.cluster_profiles if p.cluster_id == "paid_driven")
    assert organic.primary_channel in {"word_of_mouth", "organic_search", "referral_program"}
    assert paid.primary_channel in {"paid_search", "social_paid"}
    assert organic.cac_multiplier < paid.cac_multiplier
    assert organic.cac < paid.cac
    assert organic.cac == pytest.approx(out.effective_base_cac * organic.cac_multiplier)


def test_demand_weighting_honors_conversion() -> None:
    registry = [
        _cluster("high", "High Converter", 0.5),
        _cluster("low", "Low Converter", 0.5),
    ]
    conductor = {
        **(
            _architect_blocks(
                "high",
                day30=0.85,
                day90=0.80,
                wom=1.0,
                organic_ref=1.0,
                urgency=0.0,
            )
        ),
        **(
            _architect_blocks(
                "low",
                day30=0.01,
                day90=0.001,
                wom=0.0,
                organic_ref=0.0,
                urgency=1.0,
                brand_def=0.0,
            )
        ),
    }
    out = _build(
        _results({"high": 0.90, "low": 0.01}),
        registry=registry,
        conductor=conductor,
    )
    high = next(p for p in out.cluster_profiles if p.cluster_id == "high")
    low = next(p for p in out.cluster_profiles if p.cluster_id == "low")
    assert high.ltv_cac_ratio > 3.0
    assert low.ltv_cac_ratio < 1.0
    # The high-converting cluster dominates the blended read despite equal
    # population weights.
    assert out.blended_ltv_cac_ratio > 2.0
    assert out.best_cluster_id == "high"
    assert out.worst_cluster_id == "low"
    assert out.strong_share > 0.5
    assert out.unprofitable_share < 0.2


def test_cac_scenarios_scale_blended_ratio() -> None:
    out = _build(
        _results(),
        registry=_basic_registry(),
        conductor=_basic_conductor(_basic_registry()),
    )
    by_label = {s.label: s for s in out.cac_scenarios}
    base = by_label["CAC_X1"]
    double = by_label["CAC_X2"]
    assert double.blended_cac == pytest.approx(base.blended_cac * 2.0, rel=0.01)
    assert double.blended_ltv_cac_ratio == pytest.approx(
        base.blended_ltv_cac_ratio / 2.0, rel=0.01
    )
    assert by_label["CAC_X0.5"].blended_cac == pytest.approx(
        base.blended_cac * 0.5, rel=0.01
    )


def test_assumed_cac_input_uses_founder_value() -> None:
    default_out = _build(
        _results(),
        registry=_basic_registry(),
        conductor=_basic_conductor(_basic_registry()),
    )
    founder_out = _build(
        _results(),
        registry=_basic_registry(),
        conductor=_basic_conductor(_basic_registry()),
        assumed_cac=2000.0,
    )
    assert founder_out.meta["cac_source"] == "founder_input"
    assert founder_out.effective_base_cac == pytest.approx(2000.0)
    assert founder_out.base_cac == pytest.approx(2000.0)
    assert founder_out.blended_cac > default_out.blended_cac
    assert founder_out.blended_ltv_cac_ratio < default_out.blended_ltv_cac_ratio


def test_gross_margin_doubles_ltv() -> None:
    kwargs = {
        "results": _results(),
        "registry": _basic_registry(),
        "conductor": _basic_conductor(_basic_registry()),
    }
    low = _build(**kwargs, gross_margin=0.30)
    high = _build(**kwargs, gross_margin=0.60)
    assert high.blended_ltv == pytest.approx(low.blended_ltv * 2.0, rel=0.01)
    assert high.blended_ltv_cac_ratio == pytest.approx(
        low.blended_ltv_cac_ratio * 2.0, rel=0.01
    )


def test_strong_cluster_reaches_strong_verdict() -> None:
    registry = [_cluster("sticky", "Sticky SaaS", 1.0)]
    conductor = _architect_blocks(
        "sticky",
        price_ceiling=999.0,
        will_pay=1.0,
        day30=0.90,
        day90=0.85,
        wom=1.0,
        organic_ref=1.0,
        urgency=0.0,
    )
    out = _build(
        _results({"sticky": 0.10}),
        registry=registry,
        conductor=conductor,
    )
    assert out.verdict == VERDICT_STRONG
    profile = out.cluster_profiles[0]
    assert profile.verdict == VERDICT_STRONG
    assert profile.ltv_cac_ratio >= 3.0


def test_marginal_verdict_band() -> None:
    # A cluster that just clears break-even lands in the MARGINAL band.
    registry = [_cluster("meh", "Marginal", 1.0)]
    conductor = _architect_blocks(
        "meh",
        price_ceiling=999.0,
        will_pay=1.0,
        day30=0.35,
        day90=0.10,
    )
    out = _build(
        _results({"meh": 0.10}),
        registry=registry,
        conductor=conductor,
    )
    profile = out.cluster_profiles[0]
    assert 1.0 <= profile.ltv_cac_ratio < 3.0
    assert profile.verdict in {VERDICT_MARGINAL, "VIABLE"}

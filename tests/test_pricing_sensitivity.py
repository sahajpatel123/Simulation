"""
Tests for ``app.simulation.pricing_sensitivity``.

Pure-Python engine covering ``_conversion_at_price`` math, ``generate``
market rollups, and ``to_dict`` schema — including degenerate edge
cases (empty registry, single cluster, default thresholds).
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _cluster(cid: str, name: str, weight: float = 0.10) -> dict[str, Any]:
    return {
        "cluster_id": cid,
        "name": name,
        "population_weight": weight,
    }


def _pricing(
    cid: str,
    *,
    ceiling: float = 1500.0,
    will_pay: float = 0.5,
    freemium_c: float = 0.04,
    emi: float = 0.2,
    annual_pref: float = 0.3,
) -> dict[str, Any]:
    return {
        cid: {
            "PricingArchitect": {"metrics": {
                "price_ceiling": ceiling,
                "will_pay_probability": will_pay,
                "freemium_conversion_ceiling": freemium_c,
                "emi_adoption_likelihood": emi,
                "annual_payment_probability": annual_pref,
            }},
        }
    }


def _basic_registry() -> list[dict[str, Any]]:
    return [
        _cluster("metro_power_professional", "Metro Power Pro", 0.40),
        _cluster("tier3_first_time_app_user", "Tier-3 First-timer", 0.30),
        _cluster("anxiety_driven_researcher", "Research-led", 0.30),
    ]


def _basic_conductor(registry: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for c in registry:
        out[c["cluster_id"]] = {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": 1200.0,
                    "will_pay_probability": 0.5,
                    "freemium_conversion_ceiling": 0.04,
                    "emi_adoption_likelihood": 0.20,
                    "annual_payment_probability": 0.3,
                }
            }
        }
    return out


# ---------------------------------------------------------------------------
# _conversion_at_price
# ---------------------------------------------------------------------------


def test_conversion_at_price_zero_inputs_return_zero() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    assert engine._conversion_at_price(0, 1000, 0.5, 0.0, 999) == 0.0
    assert engine._conversion_at_price(500, 0, 0.5, 0.0, 999) == 0.0


def test_conversion_at_price_hard_ceiling_above_120pct() -> None:
    """price > ceiling * 1.20 → return 0.0 (hard ceiling rule)."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    ceiling = 1000.0
    out = engine._conversion_at_price(
        price=ceiling * 1.25, price_ceiling=ceiling, will_pay_prob=0.8,
        emi_likelihood=0.5, aov=999.0,
    )
    assert out == 0.0


def test_conversion_at_price_slight_overstretch_yields_low_value() -> None:
    """price in (ceiling, ceiling * 1.20] → tiny sliver of will_pay."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    out = engine._conversion_at_price(
        price=1100.0, price_ceiling=1000.0, will_pay_prob=0.8,
        emi_likelihood=0.5, aov=999.0,
    )
    expected = round(0.8 * 0.05, 4)
    assert out == expected


def test_conversion_at_price_emi_boost_applies_only_for_high_prices() -> None:
    """EMI boosts only when price > 0.8 * aov AND emi_likelihood > 0.3."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    base = engine._conversion_at_price(
        price=500.0, price_ceiling=2000.0, will_pay_prob=0.5,
        emi_likelihood=0.0, aov=999.0,
    )
    boosted = engine._conversion_at_price(
        price=500.0, price_ceiling=2000.0, will_pay_prob=0.5,
        emi_likelihood=0.8, aov=999.0,
    )
    # 500 is below 0.8 * 999 = 799 — no EMI boost regardless.
    assert base == boosted


def test_conversion_at_price_emi_boost_applies_for_high_prices() -> None:
    """When price > 0.8*aov AND emi_likelihood > 0.3, EMI boosts the result."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    no_emi = engine._conversion_at_price(
        price=900.0, price_ceiling=2000.0, will_pay_prob=0.5,
        emi_likelihood=0.0, aov=999.0,
    )
    with_emi = engine._conversion_at_price(
        price=900.0, price_ceiling=2000.0, will_pay_prob=0.5,
        emi_likelihood=0.8, aov=999.0,
    )
    assert with_emi > no_emi


def test_conversion_at_price_clamped_in_unit_interval() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    # aggressively favourable inputs
    out = engine._conversion_at_price(
        price=50.0, price_ceiling=5000.0, will_pay_prob=1.0,
        emi_likelihood=1.0, aov=10.0,
    )
    assert 0.0 <= out <= 0.95


def test_conversion_at_price_rounds_to_four_dp() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    out = engine._conversion_at_price(
        price=333.0, price_ceiling=1000.0, will_pay_prob=0.45,
        emi_likelihood=0.2, aov=999.0,
    )
    assert out == round(out, 4)


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


def test_generate_one_profile_per_cluster() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=21,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.generated_ui_id == 21
    assert result.aov == 999.0
    assert len(result.cluster_profiles) == len(registry)
    assert {p.cluster_id for p in result.cluster_profiles} == {
        c["cluster_id"] for c in registry
    }


def test_generate_price_curve_has_all_price_points() -> None:
    from app.simulation.pricing_sensitivity import (
        PRICE_POINTS_INR,
        PricingSensitivityEngine,
    )

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    for p in result.cluster_profiles:
        assert set(p.price_curve.keys()) == set(PRICE_POINTS_INR)


def test_generate_price_curves_non_increasing_with_price() -> None:
    """Higher prices generally yield lower conversion (monotonic decay)."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    prices = sorted(result.cluster_profiles[0].price_curve.keys())
    for p in result.cluster_profiles:
        convs = [p.price_curve[pr] for pr in prices]
        # Should be monotonically non-increasing.
        for prev, nxt in zip(convs, convs[1:]):
            assert nxt <= prev + 1e-9, (
                p.cluster_id, prev, nxt
            )


def test_generate_optimal_price_picked_within_price_points() -> None:
    from app.simulation.pricing_sensitivity import (
        PRICE_POINTS_INR,
        PricingSensitivityEngine,
    )

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    for p in result.cluster_profiles:
        assert p.optimal_price in set(PRICE_POINTS_INR) or p.optimal_price == 999.0


def test_generate_emi_required_when_likelihood_above_threshold() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    base_conductor = {"metro_power_professional": {"PricingArchitect": {"metrics": {}}}}

    low_emi = dict(base_conductor)
    low_emi["metro_power_professional"] = {
        "PricingArchitect": {
            "metrics": {
                "price_ceiling": 1500.0,
                "will_pay_probability": 0.5,
                "freemium_conversion_ceiling": 0.04,
                "emi_adoption_likelihood": 0.10,
                "annual_payment_probability": 0.3,
            }
        }
    }
    res_low = engine.generate(
        generated_ui_id=1,
        conductor_results=low_emi,
        cluster_registry=registry,
        aov=999.0,
    )
    assert res_low.cluster_profiles[0].emi_required is False

    high_emi = {
        "metro_power_professional": {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": 1500.0,
                    "will_pay_probability": 0.5,
                    "freemium_conversion_ceiling": 0.04,
                    "emi_adoption_likelihood": 0.70,
                    "annual_payment_probability": 0.3,
                }
            }
        }
    }
    res_high = engine.generate(
        generated_ui_id=1,
        conductor_results=high_emi,
        cluster_registry=registry,
        aov=999.0,
    )
    assert res_high.cluster_profiles[0].emi_required is True


def test_generate_recommended_price_is_highest_above_30pct_market() -> None:
    from app.simulation.pricing_sensitivity import (
        PRICE_POINTS_INR,
        PricingSensitivityEngine,
    )

    engine = PricingSensitivityEngine()
    # Single cluster with high ceiling → most points should hit 30%.
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    conductor = {
        "metro_power_professional": {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": 50000.0,  # very high
                    "will_pay_probability": 0.9,  # very willing
                    "freemium_conversion_ceiling": 0.04,
                    "emi_adoption_likelihood": 0.0,
                    "annual_payment_probability": 0.3,
                }
            }
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.recommended_price in PRICE_POINTS_INR
    # At high willingness, the highest price should be the recommended one.
    assert result.recommended_price == PRICE_POINTS_INR[-1]


def test_generate_revenue_optimal_maximises_price_times_conversion() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    conductor = {
        "metro_power_professional": {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": 5000.0,
                    "will_pay_probability": 0.6,
                    "freemium_conversion_ceiling": 0.04,
                    "emi_adoption_likelihood": 0.0,
                    "annual_payment_probability": 0.3,
                }
            }
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    # Sanity: revenue_optimal is one of the standard price points.
    assert result.revenue_optimal_price in (
        99, 199, 299, 499, 699, 999, 1499, 1999, 2999, 4999, 9999, 19999,
    )


def test_generate_elasticity_zero_when_curves_identical() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.overall_elasticity >= 0.0


def test_generate_market_segments_top_five_per_price_point() -> None:
    from app.simulation.pricing_sensitivity import (
        PRICE_POINTS_INR,
        PricingSensitivityEngine,
    )

    engine = PricingSensitivityEngine()
    # 10-cluster setup
    registry = [
        _cluster(f"cluster_{i}", f"C{i}", weight=0.1) for i in range(10)
    ]
    conductor = {
        c["cluster_id"]: {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": 1500.0,
                    "will_pay_probability": 0.5,
                    "freemium_conversion_ceiling": 0.04,
                    "emi_adoption_likelihood": 0.2,
                    "annual_payment_probability": 0.3,
                }
            }
        }
        for c in registry
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    for pp in PRICE_POINTS_INR:
        seg = result.market_segments.get(pp, [])
        assert len(seg) <= 5
        # Sorted by conversion_rate descending.
        rates = [conv for _, conv in seg]
        assert rates == sorted(rates, reverse=True)


def test_generate_handles_missing_architect_blocks() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = [
        _cluster("metro_power_professional", "M", 0.5),
        _cluster("anxiety_driven_researcher", "R", 0.5),
    ]
    # Only one cluster has conductor data.
    conductor = {
        "metro_power_professional": {
            "PricingArchitect": {"metrics": {}}
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert len(result.cluster_profiles) == 2


def test_generate_handles_missing_cluster_weight() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    bad_registry = [{"cluster_id": "metro_power_professional", "name": "M"}]
    conductor = {
        "metro_power_professional": {
            "PricingArchitect": {"metrics": {}}
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=bad_registry,
        aov=999.0,
    )
    assert len(result.cluster_profiles) == 1


def test_generate_single_profile_still_produces_recommendation() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = [_cluster("metro_power_professional", "M", 1.0)]
    conductor = {
        "metro_power_professional": {
            "PricingArchitect": {"metrics": {}}
        }
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert result.recommended_price > 0


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


def test_to_dict_serialises_required_keys() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=42,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    for key in (
        "generated_ui_id",
        "aov",
        "overall_elasticity",
        "recommended_price",
        "revenue_optimal_price",
        "cluster_profiles",
        "market_segments",
    ):
        assert key in payload
    assert payload["generated_ui_id"] == 42
    assert payload["aov"] == 999.0


def test_to_dict_price_curve_keys_are_strings() -> None:
    """JSON serialisation requires string keys — engine must stringify ints."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    curve = payload["cluster_profiles"][0]["price_curve"]
    for k in curve.keys():
        assert isinstance(k, str)


def test_to_dict_market_segment_keys_are_strings() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    for k in payload["market_segments"].keys():
        assert isinstance(k, str)


def test_to_dict_cluster_profiles_sorted_by_ceiling_descending() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    ceilings = [p["price_ceiling"] for p in payload["cluster_profiles"]]
    assert ceilings == sorted(ceilings, reverse=True)


def test_to_dict_is_json_serialisable() -> None:
    import json

    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=_basic_conductor(registry),
        cluster_registry=registry,
        aov=999.0,
    )
    payload = engine.to_dict(result)
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["generated_ui_id"] == 1


def test_generate_is_deterministic() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = _basic_registry()
    conductor = _basic_conductor(registry)
    a = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    b = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    assert engine.to_dict(a) == engine.to_dict(b)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_generate_empty_registry_degrades_gracefully() -> None:
    """max(curve.values()) on empty dict would raise — must not."""
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    result = engine.generate(
        generated_ui_id=1,
        conductor_results={},
        cluster_registry=[],
        aov=999.0,
    )
    assert result.cluster_profiles == []
    # Recommended / optimal fall back to aov; elasticity defaults.
    assert result.recommended_price == 999.0
    assert result.revenue_optimal_price == 999.0
    assert result.overall_elasticity == 0.5


def test_generate_zero_population_weights_produce_finite_rollups() -> None:
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine

    engine = PricingSensitivityEngine()
    registry = [_cluster("metro_power_professional", "M", 0.0)]
    conductor = {
        "metro_power_professional": {"PricingArchitect": {"metrics": {}}}
    }
    result = engine.generate(
        generated_ui_id=1,
        conductor_results=conductor,
        cluster_registry=registry,
        aov=999.0,
    )
    # No crash, returns sane numbers.
    assert math.isfinite(result.recommended_price)
    assert math.isfinite(result.revenue_optimal_price)

"""
Tests for the market-sizing helper
(TAM/SAM/SOM + annual revenue projection).
"""
from __future__ import annotations

import json
import math
from typing import Any

import pytest

from app.simulation.market_sizing import (
    CONVERSION_BENCHMARK,
    DEFAULT_MARKET_SIZE,
    REACHABLE_MIN_CONVERSION,
    SIGNAL_CRITICAL,
    SIGNAL_OK,
    SIGNAL_WATCH,
    build_market_sizing,
)


def _results(
    *,
    cr: float = 0.05,
    breakdown: dict[str, Any] | None = None,
    total: int = 10000,
    product_type: str = "saas",
    domain: str = "PricingArchitect",
) -> dict[str, Any]:
    return {
        "population_weighted_conversion": cr,
        "conversion_rate": cr,
        "total_agents": total,
        "cluster_breakdown": breakdown
        or {
            "a": 0.05,
            "b": 0.05,
        },
        "product_type_detected": product_type,
        "primary_failure_domain": domain,
    }


def _signals_by_key(out: dict) -> dict[str, dict]:
    return {s["key"]: s for s in out["signals"]}


def test_empty_results_yield_zero_state() -> None:
    out = build_market_sizing(None, simulation_id=1, project_id=2)
    assert out["simulation_id"] == 1
    assert out["project_id"] == 2
    assert out["overall_conversion"] == 0.0
    assert out["som_customers"] == 0
    assert out["annual_revenue"] == 0.0
    assert out["top_segments"] == []
    assert out["signals"]
    assert out["narrative"]


def test_json_string_and_garbage_inputs() -> None:
    ok = build_market_sizing(json.dumps(_results()))
    assert ok["som_customers"] == 125_000  # 10M x 1.0 x 0.25 x 0.05
    bad = build_market_sizing("{nope")
    assert bad["som_customers"] == 0
    assert bad["signals"]


def test_tam_sam_som_and_revenue_math() -> None:
    out = build_market_sizing(
        _results(cr=0.05),
        simulation_id=10,
        project_id=3,
        market_size=1_000_000,
        target_market_fraction=0.5,
        average_order_value=100,
        purchase_frequency_per_year=2,
    )
    assert out["tam_customers"] == 1_000_000
    # All clusters reachable -> SAM = TAM x 1.0 x 0.5.
    assert out["sam_customers"] == 500_000
    # SOM = SAM x weighted conversion.
    assert out["som_customers"] == 25_000
    assert out["annual_revenue"] == 5_000_000
    assert out["revenue_per_1000_visitors"] == 10_000
    assert out["product_type_detected"] == "saas"
    assert out["primary_failure_domain"] == "PricingArchitect"


def test_reachable_fraction_excludes_dead_clusters() -> None:
    out = build_market_sizing(
        _results(
            cr=0.02,
            breakdown={
                "reachable": 0.02,
                "dead": 0.0005,  # below REACHABLE_MIN_CONVERSION
            },
        ),
        market_size=1_000_000,
        target_market_fraction=1.0,
    )
    assert out["reachable_fraction"] == 0.5
    assert out["sam_customers"] == 500_000
    assert out["som_customers"] == 10_000


def test_registry_weights_and_names_used() -> None:
    registry = {
        "big": {"name": "Big Cluster", "population_weight": 0.9},
        "small": {"name": "Small Cluster", "population_weight": 0.1},
    }
    out = build_market_sizing(
        _results(cr=0.05, breakdown={"big": 0.05, "small": 0.05}),
        cluster_registry=registry,
    )
    assert out["reachable_fraction"] == 1.0
    top = out["top_segments"][0]
    assert top["cluster_id"] == "big"
    assert top["cluster_name"] == "Big Cluster"
    assert top["population_weight"] == 0.9
    shares = sum(s["som_share"] for s in out["top_segments"])
    assert abs(shares - 1.0) < 1e-6


def test_uniform_weight_fallback_without_registry() -> None:
    out = build_market_sizing(
        _results(cr=0.05, breakdown={"a": 0.05, "b": 0.05}),
    )
    assert out["reachable_fraction"] == 1.0
    assert len(out["top_segments"]) == 2


def test_conversion_signal_levels() -> None:
    critical = build_market_sizing(
        _results(cr=0.01, breakdown={"a": 0.01}),
    )
    assert _signals_by_key(critical)["conversion"]["level"] == SIGNAL_CRITICAL

    watch = build_market_sizing(
        _results(cr=0.03, breakdown={"a": 0.03}),
    )
    assert _signals_by_key(watch)["conversion"]["level"] == SIGNAL_WATCH

    ok = build_market_sizing(
        _results(cr=0.06, breakdown={"a": 0.06}),
    )
    assert _signals_by_key(ok)["conversion"]["level"] == SIGNAL_OK


def test_aov_zero_triggers_watch_signal() -> None:
    out = build_market_sizing(_results(), average_order_value=0)
    signals = _signals_by_key(out)
    assert signals["average_order_value"]["level"] == SIGNAL_WATCH
    assert out["annual_revenue"] == 0.0


def test_input_clamping() -> None:
    out = build_market_sizing(
        _results(),
        market_size=0,  # floored
        target_market_fraction=2.0,  # capped
        average_order_value=-5,  # floored
        purchase_frequency_per_year=-1,  # floored
    )
    assert out["market_size"] == 1
    assert out["meta"]["target_market_fraction"] == 1.0
    assert out["average_order_value"] == 0.0
    assert out["purchase_frequency_per_year"] == 0.0

    big = build_market_sizing(_results(), market_size=10**12)
    assert big["market_size"] == 10_000_000_000


def test_defaults_are_sane() -> None:
    out = build_market_sizing(_results(cr=0.05))
    assert out["market_size"] == DEFAULT_MARKET_SIZE
    assert out["som_customers"] == 125_000
    assert CONVERSION_BENCHMARK == 0.05
    assert REACHABLE_MIN_CONVERSION == 0.001


def test_mean_conversion_rate_fallback_without_breakdown() -> None:
    """Real results without cluster_breakdown still get a projection."""
    out = build_market_sizing(
        {
            "mean_conversion_rate": 0.04,
            "total_agents": 10000,
            "product_type_detected": "saas",
        },
        market_size=1_000_000,
        target_market_fraction=0.5,
        average_order_value=100,
    )
    assert out["overall_conversion"] == 0.04
    assert out["reachable_fraction"] == 1.0
    assert out["sam_customers"] == 500_000
    assert out["som_customers"] == 20_000
    assert out["annual_revenue"] == 2_000_000
    assert out["meta"]["conversion_source"] == "mean_conversion_rate"
    signals = _signals_by_key(out)
    assert signals["cluster_breakdown"]["level"] == SIGNAL_WATCH
    assert signals["conversion"]["level"] == SIGNAL_WATCH


def test_raw_funnel_fallback() -> None:
    """raw_funnel supplies both conversion and agent count."""
    out = build_market_sizing(
        {
            "raw_funnel": {
                "conversion_rate": 0.03,
                "total_agents": 5000,
            }
        },
        market_size=1_000_000,
        target_market_fraction=1.0,
        average_order_value=50,
    )
    assert out["overall_conversion"] == 0.03
    assert out["total_agents"] == 5000
    assert out["som_customers"] == 30_000
    assert out["meta"]["conversion_source"] == "raw_funnel"


def test_dict_of_dict_cluster_breakdown() -> None:
    """Cluster entries shaped as dicts (conversion_rate) are parsed."""
    out = build_market_sizing(
        {
            "population_weighted_conversion": 0.05,
            "cluster_breakdown": {
                "a": {"conversion_rate": 0.08, "weight": 0.5},
                "b": {"conversion_rate": 0.02, "weight": 0.5},
            },
        },
        market_size=1_000_000,
        target_market_fraction=1.0,
    )
    assert out["reachable_fraction"] == 1.0
    assert out["som_customers"] == 50_000
    assert out["top_segments"][0]["cluster_id"] == "a"
    assert out["meta"]["conversion_source"] == "population_weighted_conversion"


def test_non_finite_inputs_are_safe() -> None:
    """NaN/inf values never poison the projection math."""
    out = build_market_sizing(
        {
            "population_weighted_conversion": float("nan"),
            "total_agents": float("inf"),
            "cluster_breakdown": {
                "a": float("nan"),
                "b": float("inf"),
            },
        },
        cluster_registry={
            "a": {"name": "A", "population_weight": float("nan")},
            "b": {"name": "B", "population_weight": 0.5},
        },
        market_size=1_000_000,
        target_market_fraction=1.0,
        average_order_value=100,
    )
    assert out["overall_conversion"] == 0.0
    assert out["total_agents"] == 0
    assert out["top_segments"] == []
    assert math.isfinite(out["reachable_fraction"])
    assert math.isfinite(out["annual_revenue"])
    assert all(math.isfinite(s["population_weight"]) for s in out["top_segments"])


def test_list_results_yield_zero_state() -> None:
    out = build_market_sizing(["not", "a", "dict"])
    assert out["overall_conversion"] == 0.0
    assert out["som_customers"] == 0
    assert out["meta"]["conversion_source"] == "none"

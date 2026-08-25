"""
Tests for the pure pricing-optimization builder
(``app.simulation.pricing_optimization``).
"""
from __future__ import annotations

from typing import Any

from app.schemas.pricing_optimization import PricingOptimizationOut
from app.simulation.pricing_optimization import (
    PRICE_POINT_FACTORS,
    build_pricing_optimization,
)

AOV = 999.0


def _registry(
    clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": c["cluster_id"],
            "name": c["name"],
            "population_weight": c["population_weight"],
        }
        for c in clusters
    ]


def _conductor(
    specs: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    return {
        cid: {
            "PricingArchitect": {
                "metrics": {
                    "price_ceiling": ceiling,
                    "will_pay_probability": will_pay,
                },
                "flags": {},
            }
        }
        for cid, (ceiling, will_pay) in specs.items()
    }


def _build(
    *,
    specs: dict[str, tuple[float, float]] | None = None,
    weights: dict[str, float] | None = None,
    aov: float = AOV,
    conductor_results: dict[str, Any] | None = None,
) -> PricingOptimizationOut:
    specs = specs or {
        "high": (3000.0, 0.9),
        "mid": (1500.0, 0.6),
        "low": (500.0, 0.4),
    }
    weights = weights or {
        "high": 0.5,
        "mid": 0.3,
        "low": 0.2,
    }
    registry = _registry(
        [
            {
                "cluster_id": cid,
                "name": cid.title(),
                "population_weight": weights[cid],
            }
            for cid in specs
        ]
    )
    if conductor_results is None:
        conductor_results = _conductor(specs)
    return build_pricing_optimization(
        {"product_type_detected": "saas"},
        simulation_id=7,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.62,
        conductor_results=conductor_results,
        cluster_registry=registry,
        average_order_value=aov,
    )


def test_underpriced_when_demand_holds_at_higher_prices() -> None:
    out = _build()

    assert out.verdict == "UNDERPRICED"
    assert out.simulation_id == 7
    assert out.project_id == 10
    assert out.product_type == "saas"
    assert out.aov == AOV
    assert out.base_price == AOV
    assert out.revenue_optimal_price == 1248.75
    assert out.revenue_optimal_price > AOV * 1.15
    assert out.base_market_revenue > 0.0
    assert out.revenue_lift_vs_base_pct is not None
    assert out.revenue_lift_vs_base_pct > 0.0
    assert out.recommended_price == 1498.5
    assert out.recommendations
    assert out.key_signals
    assert out.meta["total_clusters"] == 3
    assert out.meta["clusters_with_data"] == 3
    assert out.meta["covered_weight"] == 1.0


def test_overpriced_when_ceiling_below_revenue_optimal() -> None:
    out = _build(specs={"only": (1200.0, 0.9)}, weights={"only": 1.0})

    assert out.verdict == "OVERPRICED"
    assert out.revenue_optimal_price == 749.25
    assert out.revenue_optimal_price < AOV * 0.85
    assert out.recommendations


def test_price_optimal_when_optimal_near_base() -> None:
    out = _build(specs={"only": (1498.5, 0.9)}, weights={"only": 1.0})

    assert out.verdict == "PRICE_OPTIMAL"
    assert out.revenue_optimal_price == AOV
    assert out.revenue_lift_vs_base_pct == 0.0
    assert out.recommendations


def test_insufficient_data_without_pricing_metrics() -> None:
    out = _build(
        conductor_results={
            "only": {
                "PricingArchitect": {
                    "metrics": {
                        "price_ceiling": 0.0,
                        "will_pay_probability": 0.0,
                    },
                    "flags": {},
                }
            }
        },
        specs={"only": (0.0, 0.0)},
        weights={"only": 1.0},
    )

    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.revenue_optimal_price is None
    assert out.recommended_price is None
    assert out.overall_elasticity is None
    assert out.meta["clusters_with_data"] == 0
    assert out.recommendations == [
        "Not enough pricing signal in this run — pricing metrics are "
        "missing for every cluster, so no demand curve could be built."
    ]


def test_zero_base_demand_is_overpriced_not_insufficient() -> None:
    # Ceiling below the base price collapses base demand to zero, but the
    # lowest probed point still converts — that is a pricing signal, so the
    # read must be OVERPRICED with a concrete revenue-optimal price rather
    # than INSUFFICIENT_DATA.
    out = _build(specs={"low": (100.0, 0.9)}, weights={"low": 1.0})

    assert out.verdict == "OVERPRICED"
    assert out.revenue_optimal_price == round(AOV * 0.10, 2)
    assert out.base_market_conversion == 0.0
    assert out.base_market_revenue == 0.0
    assert out.revenue_lift_vs_base_pct is None
    assert out.recommended_price is None
    assert out.meta["clusters_with_data"] == 1
    assert any(
        "zero" in r.lower() or "lower-priced" in r.lower()
        for r in out.recommendations
    )


def test_no_demand_at_any_probed_price_stays_insufficient() -> None:
    # Ceiling so low that even 0.10x AOV overshoots it: no positive revenue
    # anywhere, so the verdict is INSUFFICIENT_DATA — but the explanation
    # must not claim the pricing metrics are missing.
    out = _build(specs={"low": (50.0, 0.9)}, weights={"low": 1.0})

    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.revenue_optimal_price is None
    assert out.revenue_at_optimal == 0.0
    assert out.meta["clusters_with_data"] == 1
    assert out.recommendations[0].startswith(
        "No positive demand at any probed price point"
    )


def test_signal_quality_echoed_in_meta() -> None:
    out = _build()

    assert out.meta["signal_quality"] == 0.62


def test_elasticity_is_elastic_for_tight_ceilings() -> None:
    out = _build(specs={"only": (AOV * 1.2, 0.9)}, weights={"only": 1.0})
    assert out.overall_elasticity is not None
    assert out.overall_elasticity < -1.0


def test_elasticity_is_inelastic_for_high_ceilings() -> None:
    out = _build(specs={"only": (AOV * 3.0, 0.9)}, weights={"only": 1.0})
    assert out.overall_elasticity is not None
    assert -1.0 < out.overall_elasticity < 0.0


def test_price_points_sorted_and_include_base() -> None:
    out = _build()

    prices = [p.price for p in out.price_points]
    assert prices == sorted(prices)
    assert AOV in prices
    assert len(prices) == len(PRICE_POINT_FACTORS)
    assert prices[0] == round(AOV * 0.10, 2)
    assert prices[-1] == round(AOV * 5.00, 2)
    assert all(p.market_revenue >= 0.0 for p in out.price_points)


def test_cluster_profile_flags_at_ceiling() -> None:
    out = _build()

    low = next(c for c in out.cluster_profiles if c.cluster_id == "low")
    assert low.at_ceiling is True
    assert low.ceiling_gap_pct == 49.9
    assert low.price_ceiling == 500.0

    high = next(c for c in out.cluster_profiles if c.cluster_id == "high")
    assert high.at_ceiling is False
    assert high.optimal_price > AOV


def test_schema_round_trip_from_model_dump() -> None:
    out = _build()
    parsed = PricingOptimizationOut.model_validate(out.model_dump())
    assert parsed == out


def test_zero_aov_returns_insufficient() -> None:
    out = _build(aov=0.0)
    assert out.verdict == "INSUFFICIENT_DATA"
    assert out.price_points == []

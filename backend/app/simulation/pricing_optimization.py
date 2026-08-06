"""
Pure pricing-optimization analysis for completed simulation results.

Answers the founder's "should I charge more or less?" question by turning the
``PricingArchitect`` per-cluster metrics into a deterministic demand curve:

* **Price ceiling** — the max each cluster will pay for the product.
* **Will-pay probability** — how likely the cluster converts at or below
  its ceiling.
* **Demand curve** — for each AOV-relative price point, conversion per
  cluster decays linearly inside the ceiling (``1 - 0.85 * price/ceiling``),
  drops to 5% of will-pay just above the ceiling, and collapses at >1.2x
  the ceiling. The market conversion is the population-weighted blend over
  the covered registry weight, so partial/legacy conductor payloads cannot
  silently understate demand.
* **Revenue-optimal price** — the price point that maximises
  ``price x market conversion x cohort size`` (ties resolve to the lower
  price — same revenue at a friendlier price).
* **Recommended price** — the highest price that retains at least half of
  base-price demand.
* **Arc elasticity** — measured between 0.8x and 1.2x the base price, so a
  founder sees how much demand moves for a ±20% price change.

The verdict buckets the revenue-optimal price against the base price:
``UNDERPRICED`` (optimal >= 1.15x base), ``OVERPRICED`` (optimal <= 0.85x
base, including runs where demand at the base price is effectively zero),
``PRICE_OPTIMAL`` otherwise, ``INSUFFICIENT_DATA`` when no cluster has
usable pricing metrics or no probed price point yields positive revenue.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies ``results``, ``conductor_results`` (per-cluster architect metrics)
and ``cluster_registry``; all arithmetic is deterministic.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.pricing_optimization import (
    ClusterPriceProfile,
    PricePoint,
    PricingOptimizationOut,
    VERDICT_INSUFFICIENT,
    VERDICT_OVERPRICED,
    VERDICT_PRICE_OPTIMAL,
    VERDICT_UNDERPRICED,
)

# Cohort size the simulation pipeline models (10,000 consumers).
COHORT_SIZE: int = 10000

# AOV-relative price points probed by the demand curve. 1.0 is the base
# price (the environment's average order value).
PRICE_POINT_FACTORS: tuple[float, ...] = (
    0.10, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00, 3.00, 5.00,
)

# Conversion collapses once price exceeds this multiple of the ceiling.
CEILING_OVERSHOOT_LIMIT: float = 1.20

# Conversion share surviving a modest overshoot above the ceiling.
OVERSTRETCH_CONVERSION_SHARE: float = 0.05

# Demand decay slope inside the ceiling (mirrors the UI pricing engine).
CEILING_DECAY_SLOPE: float = 0.85

# Recommended price = highest price retaining this share of base demand.
RECOMMENDED_DEMAND_RETENTION: float = 0.50

# Verdict hysteresis: flag a mismatch only when the revenue-optimal price
# moves by at least 15% from the base price.
VERDICT_RAISE_THRESHOLD: float = 1.15
VERDICT_LOWER_THRESHOLD: float = 0.85

# Price anchors for the arc-elasticity measurement (±20% around base).
ELASTICITY_LOW_FACTOR: float = 0.80
ELASTICITY_HIGH_FACTOR: float = 1.20

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Cluster count above which at-ceiling pricing becomes a strategic flag.
AT_CEILING_WARN_COUNT: int = 5


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _pricing_metrics(
    conductor_results: dict[str, Any] | None,
    cluster_id: str,
) -> dict[str, Any]:
    """Extract the PricingArchitect metrics block for one cluster."""
    if not conductor_results:
        return {}
    cluster_block = conductor_results.get(cluster_id)
    if not isinstance(cluster_block, dict):
        return {}
    pricing = cluster_block.get("PricingArchitect")
    if not isinstance(pricing, dict):
        return {}
    metrics = pricing.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _conversion_at_price(
    price: float,
    price_ceiling: float,
    will_pay_probability: float,
) -> float:
    """Deterministic conversion share for one cluster at ``price``."""
    if price <= 0 or price_ceiling <= 0 or will_pay_probability <= 0:
        return 0.0
    ratio = price / price_ceiling
    if ratio > CEILING_OVERSHOOT_LIMIT:
        return 0.0
    if ratio > 1.0:
        return round(
            will_pay_probability * OVERSTRETCH_CONVERSION_SHARE, 6
        )
    decayed = will_pay_probability * max(
        0.0, 1.0 - ratio * CEILING_DECAY_SLOPE
    )
    return round(max(0.0, min(1.0, decayed)), 6)


def _price_points(average_order_value: float) -> list[float]:
    """AOV-relative candidate prices, sorted ascending, base price included."""
    if average_order_value <= 0:
        return []
    seen: set[float] = set()
    points: list[float] = []
    for factor in PRICE_POINT_FACTORS:
        price = round(average_order_value * factor, 2)
        if price <= 0 or price in seen:
            continue
        seen.add(price)
        points.append(price)
    return sorted(points)


def _fmt_price(price: float) -> str:
    if price >= 100:
        return f"{price:,.0f}"
    return f"{price:,.2f}"


def _market_conversion(
    price: float,
    clusters: list[ClusterPriceProfile],
) -> float:
    """Population-weighted blend over clusters with usable pricing data."""
    covered_weight = 0.0
    weighted_conv = 0.0
    for cluster in clusters:
        if cluster.price_ceiling <= 0 or cluster.will_pay_probability <= 0:
            continue
        conv = _conversion_at_price(
            price,
            cluster.price_ceiling,
            cluster.will_pay_probability,
        )
        weighted_conv += cluster.population_weight * conv
        covered_weight += cluster.population_weight
    if covered_weight <= 0:
        return 0.0
    return round(weighted_conv / covered_weight, 6)


def _cluster_optimal_price(
    price_points: list[float],
    price_ceiling: float,
    will_pay_probability: float,
) -> float:
    """Per-cluster revenue-optimal price (ties resolve to the lower price)."""
    best_price = 0.0
    best_revenue = -1.0
    for price in price_points:
        conv = _conversion_at_price(price, price_ceiling, will_pay_probability)
        revenue = price * conv
        if revenue > best_revenue:
            best_revenue = revenue
            best_price = price
    return best_price


def build_pricing_optimization(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    conductor_results: dict[str, Any] | None = None,
    cluster_registry: list[dict[str, Any]] | None = None,
    average_order_value: float = 999.0,
) -> PricingOptimizationOut:
    """Compose the pricing-optimization read from completed results.

    Args:
        results: Simulation ``results_json`` (used for ``product_type``).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any (echoed
            into ``meta.signal_quality`` so founders can weigh the read).
        conductor_results: Per-cluster architect output blocks
            (``{cluster_id: {architect: {"metrics": ...}}}``).
        cluster_registry: List of ``{cluster_id, name, population_weight}``.
        average_order_value: The environment's assumed AOV (base price).
    """
    payload = _coerce_results(results)
    aov = max(0.0, _safe_float(average_order_value, 999.0))
    product_type = str(
        payload.get("product_type_detected", "saas") or "saas"
    )

    registry: list[dict[str, Any]] = cluster_registry or []
    price_points = _price_points(aov)

    clusters: list[ClusterPriceProfile] = []
    for entry in registry:
        cid = str(entry.get("cluster_id", ""))
        if not cid:
            continue
        metrics = _pricing_metrics(conductor_results, cid)
        ceiling = max(0.0, _safe_float(metrics.get("price_ceiling")))
        will_pay = max(
            0.0, min(1.0, _safe_float(metrics.get("will_pay_probability")))
        )
        weight = max(
            0.0, _safe_float(entry.get("population_weight"))
        )
        conv_at_base = (
            _conversion_at_price(aov, ceiling, will_pay)
            if price_points
            else 0.0
        )
        clusters.append(
            ClusterPriceProfile(
                cluster_id=cid,
                cluster_name=str(entry.get("name") or cid),
                population_weight=weight,
                price_ceiling=round(ceiling, 2),
                will_pay_probability=round(will_pay, 4),
                conversion_at_base_price=conv_at_base,
                optimal_price=(
                    _cluster_optimal_price(price_points, ceiling, will_pay)
                    if price_points
                    else 0.0
                ),
                at_ceiling=aov > ceiling > 0,
                ceiling_gap_pct=(
                    round((aov - ceiling) / aov * 100.0, 1)
                    if aov > 0 and ceiling > 0
                    else 0.0
                ),
            )
        )

    usable = [
        c for c in clusters
        if c.price_ceiling > 0 and c.will_pay_probability > 0
    ]
    base_price = round(aov, 2)

    curve: list[PricePoint] = []
    base_conversion = 0.0
    base_revenue = 0.0
    if price_points and aov > 0:
        base_conversion = _market_conversion(aov, clusters)
        base_revenue = round(
            aov * base_conversion * COHORT_SIZE, 2
        )
        for price in price_points:
            conversion = _market_conversion(price, clusters)
            revenue = round(price * conversion * COHORT_SIZE, 2)
            curve.append(
                PricePoint(
                    price=price,
                    market_conversion=conversion,
                    market_revenue=revenue,
                    demand_retained_pct=(
                        round(
                            conversion / base_conversion * 100.0, 1
                        )
                        if base_conversion > 0
                        else 0.0
                    ),
                )
            )

    revenue_optimal_price: float | None = None
    revenue_at_optimal = 0.0
    if curve:
        best_revenue = 0.0
        for point in curve:
            if point.market_revenue > best_revenue:
                best_revenue = point.market_revenue
                revenue_optimal_price = point.price
                revenue_at_optimal = point.market_revenue

    # Arc elasticity between 0.8x and 1.2x the base price.
    overall_elasticity: float | None = None
    if aov > 0 and usable:
        q_low = _market_conversion(aov * ELASTICITY_LOW_FACTOR, clusters)
        q_high = _market_conversion(aov * ELASTICITY_HIGH_FACTOR, clusters)
        q_avg = (q_low + q_high) / 2.0
        if q_avg > 0:
            p_delta_pct = (
                (ELASTICITY_HIGH_FACTOR - ELASTICITY_LOW_FACTOR)
                / ((ELASTICITY_HIGH_FACTOR + ELASTICITY_LOW_FACTOR) / 2.0)
            )
            overall_elasticity = round(
                ((q_high - q_low) / q_avg) / p_delta_pct, 2
            )

    if not price_points or not usable or revenue_optimal_price is None:
        verdict = VERDICT_INSUFFICIENT
    elif revenue_optimal_price >= aov * VERDICT_RAISE_THRESHOLD:
        verdict = VERDICT_UNDERPRICED
    elif revenue_optimal_price <= aov * VERDICT_LOWER_THRESHOLD:
        verdict = VERDICT_OVERPRICED
    else:
        verdict = VERDICT_PRICE_OPTIMAL

    recommended_price: float | None = None
    if base_conversion > 0 and curve:
        retention_target = base_conversion * RECOMMENDED_DEMAND_RETENTION
        for point in curve:
            if point.market_conversion >= retention_target:
                recommended_price = point.price

    revenue_lift_pct: float | None = None
    if (
        revenue_at_optimal > 0
        and base_revenue > 0
        and verdict != VERDICT_INSUFFICIENT
    ):
        revenue_lift_pct = round(
            (revenue_at_optimal - base_revenue) / base_revenue * 100.0, 1
        )

    at_ceiling_count = sum(1 for c in clusters if c.at_ceiling)
    recommendations = _build_recommendations(
        verdict=verdict,
        aov=aov,
        revenue_optimal_price=revenue_optimal_price,
        revenue_lift_pct=revenue_lift_pct,
        overall_elasticity=overall_elasticity,
        base_conversion=base_conversion,
        optimal_conversion=_market_conversion(
            revenue_optimal_price or aov, clusters
        ),
        at_ceiling_count=at_ceiling_count,
        clusters_with_data=len(usable),
        total_clusters=len(clusters),
        top_at_ceiling_cluster=_top_at_ceiling_cluster(clusters),
    )

    severity = _verdict_severity(verdict)
    key_signals = _build_key_signals(
        verdict=verdict,
        severity=severity,
        revenue_optimal_price=revenue_optimal_price,
        revenue_lift_pct=revenue_lift_pct,
        overall_elasticity=overall_elasticity,
        at_ceiling_count=at_ceiling_count,
    )

    return PricingOptimizationOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type,
        aov=round(aov, 2),
        base_price=base_price,
        base_market_conversion=base_conversion,
        base_market_revenue=base_revenue,
        revenue_optimal_price=revenue_optimal_price,
        revenue_at_optimal=round(revenue_at_optimal, 2),
        revenue_lift_vs_base_pct=revenue_lift_pct,
        recommended_price=recommended_price,
        overall_elasticity=overall_elasticity,
        verdict=verdict,
        price_points=curve,
        cluster_profiles=sorted(
            clusters, key=lambda c: (-c.population_weight, c.cluster_id)
        ),
        recommendations=recommendations,
        key_signals=key_signals,
        meta={
            "cohort_size": COHORT_SIZE,
            "signal_quality": (
                round(signal_quality, 4)
                if signal_quality is not None
                else None
            ),
            "total_clusters": len(clusters),
            "clusters_with_data": len(usable),
            "covered_weight": round(
                sum(c.population_weight for c in usable), 4
            ),
            "demand_retention_rule": RECOMMENDED_DEMAND_RETENTION,
            "elasticity_measurement": "arc_0.8x_to_1.2x",
        },
    )


def _verdict_severity(verdict: str) -> str:
    if verdict == VERDICT_PRICE_OPTIMAL:
        return SIGNAL_OK
    if verdict == VERDICT_INSUFFICIENT:
        return SIGNAL_WATCH
    return SIGNAL_WATCH


def _top_at_ceiling_cluster(
    clusters: list[ClusterPriceProfile],
) -> ClusterPriceProfile | None:
    at_ceiling = [c for c in clusters if c.at_ceiling]
    if not at_ceiling:
        return None
    return max(
        at_ceiling,
        key=lambda c: (c.population_weight, c.price_ceiling),
    )


def _build_recommendations(
    *,
    verdict: str,
    aov: float,
    revenue_optimal_price: float | None,
    revenue_lift_pct: float | None,
    overall_elasticity: float | None,
    base_conversion: float,
    optimal_conversion: float,
    at_ceiling_count: int,
    clusters_with_data: int,
    total_clusters: int,
    top_at_ceiling_cluster: ClusterPriceProfile | None,
) -> list[str]:
    if verdict == VERDICT_INSUFFICIENT:
        if clusters_with_data:
            return [
                "No positive demand at any probed price point — even the "
                "lowest tested price sits above every cluster's "
                "willingness-to-pay ceiling, so no revenue-optimal price "
                "could be found."
            ]
        return [
            "Not enough pricing signal in this run — pricing metrics are "
            "missing for every cluster, so no demand curve could be built."
        ]

    recommendations: list[str] = []
    assert revenue_optimal_price is not None
    if verdict == VERDICT_UNDERPRICED:
        if revenue_lift_pct is not None:
            recommendations.append(
                f"Raising price from {_fmt_price(aov)} to "
                f"{_fmt_price(revenue_optimal_price)} could lift cohort "
                f"revenue ~{revenue_lift_pct:.1f}% while demand-weighted "
                f"conversion moves from {base_conversion:.1%} to "
                f"{optimal_conversion:.1%}."
            )
        else:
            recommendations.append(
                f"Demand holds at {_fmt_price(revenue_optimal_price)} — "
                "raising the price is worth testing."
            )
    elif verdict == VERDICT_OVERPRICED:
        if revenue_lift_pct is not None:
            recommendations.append(
                f"Lowering price from {_fmt_price(aov)} toward "
                f"{_fmt_price(revenue_optimal_price)} could add "
                f"~{revenue_lift_pct:.1f}% cohort revenue — demand "
                f"currently collapses before the base price is reached."
            )
        else:
            recommendations.append(
                f"Demand at the current price is effectively zero — the "
                f"revenue-optimal price is "
                f"{_fmt_price(revenue_optimal_price)}. Lower the price or "
                "add a lower-priced tier."
            )
    else:
        recommendations.append(
            "Current price is close to the revenue-optimal point — keep "
            "pricing, and re-test after any positioning or audience change."
        )

    if overall_elasticity is not None:
        direction = (
            "elastic" if overall_elasticity < -1.0 else "inelastic"
        )
        recommendations.append(
            f"Demand around the current price is {direction} "
            f"(arc elasticity {overall_elasticity:+.2f}): a ±20% price move "
            "shifts demand-weighted conversion materially."
        )

    if at_ceiling_count and total_clusters:
        detail = ""
        if top_at_ceiling_cluster is not None:
            detail = (
                f" e.g. {top_at_ceiling_cluster.cluster_name} "
                f"(ceiling {_fmt_price(top_at_ceiling_cluster.price_ceiling)})"
            )
        recommendations.append(
            f"{at_ceiling_count} of {total_clusters} clusters are priced "
            f"above their willingness-to-pay ceiling{detail} — consider "
            "EMI, freemium, or a lower-tier option to capture them."
        )
    return recommendations


def _build_key_signals(
    *,
    verdict: str,
    severity: str,
    revenue_optimal_price: float | None,
    revenue_lift_pct: float | None,
    overall_elasticity: float | None,
    at_ceiling_count: int,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = [
        {
            "label": "verdict",
            "value": verdict,
            "severity": severity,
            "display": (
                f"Price strategy: {verdict.replace('_', ' ').title()}"
            ),
        }
    ]
    if verdict != VERDICT_INSUFFICIENT and revenue_optimal_price is not None:
        signals.append(
            {
                "label": "revenue_optimal_price",
                "value": revenue_optimal_price,
                "severity": severity,
                "display": (
                    f"Revenue-optimal price: "
                    f"{_fmt_price(revenue_optimal_price)}"
                ),
            }
        )
        signals.append(
            {
                "label": "revenue_lift_vs_base_pct",
                "value": (
                    f"{revenue_lift_pct:.1f}%"
                    if revenue_lift_pct is not None
                    else "n/a"
                ),
                "severity": (
                    SIGNAL_OK
                    if (revenue_lift_pct or 0.0) >= 0.0
                    else SIGNAL_WATCH
                ),
                "display": (
                    f"Revenue lift vs base: "
                    f"{revenue_lift_pct:.1f}%"
                    if revenue_lift_pct is not None
                    else "Revenue lift vs base: n/a"
                ),
            }
        )
    if overall_elasticity is not None:
        signals.append(
            {
                "label": "overall_elasticity",
                "value": overall_elasticity,
                "severity": (
                    SIGNAL_WATCH
                    if overall_elasticity < -1.0
                    else SIGNAL_OK
                ),
                "display": f"Price elasticity: {overall_elasticity:+.2f}",
            }
        )
    if at_ceiling_count:
        signals.append(
            {
                "label": "at_ceiling_cluster_count",
                "value": at_ceiling_count,
                "severity": (
                    SIGNAL_CRITICAL
                    if at_ceiling_count >= AT_CEILING_WARN_COUNT
                    else SIGNAL_WATCH
                ),
                "display": (
                    f"{at_ceiling_count} clusters priced above "
                    "willingness-to-pay"
                ),
            }
        )
    return signals


__all__ = [
    "COHORT_SIZE",
    "PRICE_POINT_FACTORS",
    "build_pricing_optimization",
]

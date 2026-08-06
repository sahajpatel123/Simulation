"""
Pure founder-brief builder for completed simulation results.

Consolidates three existing deterministic reads into one digest:

* ``build_simulation_quality`` — trust score over persisted payload
  integrity.
* ``build_launch_checklist`` — readiness score over coverage, signal
  quality, assumptions and funnel sanity.
* ``build_market_sizing`` — TAM / SAM / SOM and annual revenue.

The brief returns a single verdict (launch-checklist verdict), the key
numbers a founder wants in one glance, and the top recommendations from
the underlying reads (deduplicated, order-preserving).

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from typing import Any

from app.schemas.founder_brief import FounderBriefOut
from app.schemas.market_sizing import MarketSizingOut
from app.simulation.launch_checklist import build_launch_checklist
from app.simulation.market_sizing import (
    DEFAULT_AVERAGE_ORDER_VALUE,
    DEFAULT_MARKET_SIZE,
    DEFAULT_PURCHASE_FREQUENCY_PER_YEAR,
    DEFAULT_TARGET_MARKET_FRACTION,
    build_market_sizing,
)
from app.simulation.simulation_quality import build_simulation_quality


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def build_founder_brief(
    results: Any,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    visible_assumption_count: int | None = None,
    product_type: str = "saas",
    cluster_registry: list[dict[str, Any]] | None = None,
    market_size: int = DEFAULT_MARKET_SIZE,
    target_market_fraction: float = DEFAULT_TARGET_MARKET_FRACTION,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    purchase_frequency_per_year: float = (
        DEFAULT_PURCHASE_FREQUENCY_PER_YEAR
    ),
) -> FounderBriefOut:
    """Compose the founder brief from a completed run.

    Args:
        results: Simulation ``results_json``.
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
        visible_assumption_count: Number of visible project assumptions.
        product_type: Detected product type for the run.
        cluster_registry: Registry entries for coverage/market sizing.
        market_size: TAM input for market sizing.
        target_market_fraction: Launch-segment fraction.
        average_order_value: Revenue per converted customer.
        purchase_frequency_per_year: Purchases per customer per year.
    """
    quality = build_simulation_quality(
        simulation_id=simulation_id,
        project_id=project_id,
        base_results=results,
        status=status,
        signal_quality=signal_quality,
    )
    registry_dict = (
        {
            str(item.get("cluster_id")): {
                "name": item.get("name", ""),
                "population_weight": item.get("population_weight", 0.0),
            }
            for item in (cluster_registry or [])
        }
        if cluster_registry
        else None
    )
    readiness = build_launch_checklist(
        results,
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        signal_quality=signal_quality,
        visible_assumption_count=visible_assumption_count,
        product_type=product_type,
        cluster_registry=cluster_registry,
    )
    market_payload = build_market_sizing(
        results,
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        market_size=market_size,
        target_market_fraction=target_market_fraction,
        average_order_value=average_order_value,
        purchase_frequency_per_year=purchase_frequency_per_year,
        cluster_registry=registry_dict,
        signal_quality=signal_quality,
    )
    market = MarketSizingOut(**market_payload)

    headline = quality.headline_conversion
    if headline is None and market.overall_conversion > 0:
        headline = market.overall_conversion

    recommendations = _dedupe(
        list(quality.recommendations)
        + list(readiness.recommendations)
        + ([market.narrative] if market.narrative else [])
    )[:8]

    return FounderBriefOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=readiness.product_type,
        headline_conversion=headline,
        trust_score=quality.trust_score,
        readiness_score=readiness.readiness_score,
        verdict=readiness.verdict,
        signal_quality=signal_quality,
        visible_assumptions=visible_assumption_count,
        tam_customers=market.tam_customers,
        sam_customers=market.sam_customers,
        som_customers=market.som_customers,
        annual_revenue=round(market.annual_revenue, 2),
        top_recommendations=recommendations,
        meta={
            "quality_checks": quality.summary.total_checks,
            "quality_trust_score": quality.trust_score,
            "readiness_items": readiness.summary.total_items,
            "readiness_score": readiness.readiness_score,
            "market_som_customers": market.som_customers,
            "market_annual_revenue": round(market.annual_revenue, 2),
        },
    )


__all__ = ["build_founder_brief"]

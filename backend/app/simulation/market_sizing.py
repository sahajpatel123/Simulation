"""
Pure market-sizing helpers for a completed simulation.

Answers the founder's "how big is this opportunity?" question
from the same weighted conversion the rest of the dashboard
uses:

* ``TAM`` — the total addressable market the founder wants to
  reason about (explicit ``market_size`` input, default 10M).
* ``SAM`` — TAM x the population-weighted share of clusters the
  product can actually reach (conversion >= 0.1%) x the target
  market fraction (how much of that reachable population is in
  the launch segment / geography).
* ``SOM`` — SAM x the simulation's weighted conversion rate
  (the obtainable share given the product as it currently is).
* ``annual_revenue`` — SOM customers x average order value x
  purchases per year.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The
route layer supplies the completed ``results_json`` plus an
optional ``cluster_registry`` (cluster id -> name + population
weight); when weights are missing the helper falls back to a
uniform weighting so the numbers still come out sensible.
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any

from app.schemas.market_sizing import (
    MarketSizingOut,
    MarketSizingSignal,
    SegmentProjection,
)

# Defaults / caps for the founder-facing query params.
DEFAULT_MARKET_SIZE: int = 10_000_000
MIN_MARKET_SIZE: int = 1
MAX_MARKET_SIZE: int = 10_000_000_000
DEFAULT_TARGET_MARKET_FRACTION: float = 0.25
MIN_TARGET_MARKET_FRACTION: float = 0.01
MAX_TARGET_MARKET_FRACTION: float = 1.0
DEFAULT_AVERAGE_ORDER_VALUE: float = 0.0
DEFAULT_PURCHASE_FREQUENCY_PER_YEAR: float = 1.0

# Clusters below this conversion are treated as unreachable
# for this product (structurally not servable yet).
REACHABLE_MIN_CONVERSION: float = 0.001

# Conversion benchmark used for the traffic-light signals.
CONVERSION_BENCHMARK: float = 0.05
CONVERSION_WATCH_THRESHOLD: float = 0.02

# How many clusters to surface in the top-segments list.
TOP_SEGMENTS_LIMIT: int = 3

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _cluster_rate(raw: Any) -> float:
    """Extract a clamped conversion rate from a cluster entry."""
    if isinstance(raw, dict):
        rate = _safe_float(
            raw.get("conversion_rate", raw.get("conversion")),
        )
    else:
        rate = _safe_float(raw)
    return max(0.0, min(1.0, rate))


def _cluster_weight(
    cluster_id: str,
    registry: dict[str, dict[str, Any]] | None,
) -> float | None:
    if not registry:
        return None
    entry = registry.get(cluster_id)
    if not isinstance(entry, dict):
        return None
    weight = _safe_float(entry.get("population_weight"))
    if weight <= 0:
        return None
    return min(weight, 1.0)


def _cluster_name(
    cluster_id: str,
    registry: dict[str, dict[str, Any]] | None,
) -> str:
    if registry and isinstance(registry.get(cluster_id), dict):
        name = registry[cluster_id].get("name")
        if name:
            return str(name)
    return cluster_id


def _build_signals(
    *,
    overall_conversion: float,
    reachable_fraction: float,
    average_order_value: float,
    has_cluster_data: bool,
) -> list[MarketSizingSignal]:
    """Compose the traffic-light signals for the digest."""
    signals: list[MarketSizingSignal] = []

    if not has_cluster_data or overall_conversion <= 0:
        signals.append(
            MarketSizingSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_CRITICAL,
                message=(
                    "No usable conversion data in this simulation "
                    "— re-run before trusting the projection."
                ),
            )
        )
    elif overall_conversion >= CONVERSION_BENCHMARK:
        signals.append(
            MarketSizingSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_OK,
                message=(
                    f"Conversion of {overall_conversion:.2%} is "
                    f"at or above the {CONVERSION_BENCHMARK:.0%} "
                    "benchmark."
                ),
            )
        )
    elif overall_conversion >= CONVERSION_WATCH_THRESHOLD:
        signals.append(
            MarketSizingSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_WATCH,
                message=(
                    f"Conversion of {overall_conversion:.2%} is "
                    "below the 5% benchmark — validate the offer "
                    "before scaling spend."
                ),
            )
        )
    else:
        signals.append(
            MarketSizingSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_CRITICAL,
                message=(
                    f"Conversion of {overall_conversion:.2%} is "
                    "very low — fix core product friction before "
                    "projecting revenue."
                ),
            )
        )

    if has_cluster_data and reachable_fraction < 0.5:
        signals.append(
            MarketSizingSignal(
                key="reachable_fraction",
                label="Reachable market",
                level=SIGNAL_WATCH,
                message=(
                    f"Only {reachable_fraction:.0%} of the target "
                    "population is reachable at current conversion "
                    "— the product misses a large share of clusters."
                ),
            )
        )

    if average_order_value <= 0:
        signals.append(
            MarketSizingSignal(
                key="average_order_value",
                label="Average order value",
                level=SIGNAL_WATCH,
                message=(
                    "Set an average order value to project annual "
                    "revenue."
                ),
            )
        )

    return signals


def build_market_sizing(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    market_size: int = DEFAULT_MARKET_SIZE,
    target_market_fraction: float = DEFAULT_TARGET_MARKET_FRACTION,
    average_order_value: float = DEFAULT_AVERAGE_ORDER_VALUE,
    purchase_frequency_per_year: float = (
        DEFAULT_PURCHASE_FREQUENCY_PER_YEAR
    ),
    cluster_registry: dict[str, dict[str, Any]] | None = None,
    signal_quality: float | None = None,
) -> dict:
    """Compose the market-sizing payload for a completed run.

    Args:
        results: simulation ``results_json`` (dict or JSON
            string). Expected keys: ``population_weighted_conversion``
            / ``conversion_rate``, ``cluster_breakdown``
            (cluster id -> rate or dict), ``total_agents``,
            ``product_type_detected``, ``primary_failure_domain``.
        market_size: TAM the founder wants to reason about.
        target_market_fraction: share of the reachable market
            inside the launch segment / geography.
        average_order_value: revenue per converted customer.
        purchase_frequency_per_year: purchases per customer per
            year.
        cluster_registry: optional cluster id -> ``name`` +
            ``population_weight`` (sums to ~1.0). When missing,
            clusters are weighted uniformly.
        signal_quality: simulation signal quality (0.0 - 1.0)
            forwarded for transparency.

    Returns:
        Dict matching :class:`MarketSizingOut`.
    """
    data = _coerce_results(results)

    effective_market_size = max(
        MIN_MARKET_SIZE,
        min(MAX_MARKET_SIZE, _safe_int(market_size, DEFAULT_MARKET_SIZE)),
    )
    effective_fraction = max(
        MIN_TARGET_MARKET_FRACTION,
        min(
            MAX_TARGET_MARKET_FRACTION,
            _safe_float(target_market_fraction, DEFAULT_TARGET_MARKET_FRACTION),
        ),
    )
    effective_aov = max(0.0, _safe_float(average_order_value))
    effective_frequency = max(
        0.0, _safe_float(purchase_frequency_per_year),
    )

    overall_conversion = max(
        0.0,
        min(
            1.0,
            _safe_float(
                data.get(
                    "population_weighted_conversion",
                    data.get("conversion_rate"),
                )
            ),
        ),
    )
    total_agents = max(
        0, _safe_int(data.get("total_agents")),
    )
    product_type = str(data.get("product_type_detected") or "")
    failure_domain = str(data.get("primary_failure_domain") or "unknown")

    # ---- Cluster reach + segment projections ----------------------
    raw_breakdown = data.get("cluster_breakdown")
    breakdown: dict[str, Any] = (
        raw_breakdown
        if isinstance(raw_breakdown, dict)
        else {}
    )

    entries: list[tuple[str, float, float]] = []
    reachable_weight = 0.0
    total_weight = 0.0
    weighted_conversion_sum = 0.0

    if breakdown:
        uniform_weight = 1.0 / max(len(breakdown), 1)
        for cluster_id, raw_rate in breakdown.items():
            cid = str(cluster_id)
            rate = _cluster_rate(raw_rate)
            weight = _cluster_weight(cid, cluster_registry)
            if weight is None:
                weight = uniform_weight
            total_weight += weight
            weighted_conversion_sum += weight * rate
            if rate >= REACHABLE_MIN_CONVERSION:
                reachable_weight += weight
            entries.append((cid, rate, weight))

    has_cluster_data = bool(entries)
    reachable_fraction = (
        max(0.0, min(1.0, reachable_weight / total_weight))
        if total_weight > 0
        else 0.0
    )
    weighted_conversion = (
        weighted_conversion_sum / total_weight
        if total_weight > 0
        else overall_conversion
    )
    if overall_conversion <= 0:
        overall_conversion = max(0.0, min(1.0, weighted_conversion))

    # ---- TAM / SAM / SOM ------------------------------------------
    tam_customers = effective_market_size
    sam_customers = round(
        tam_customers * reachable_fraction * effective_fraction
    )
    som_customers = round(sam_customers * overall_conversion)
    annual_revenue = (
        som_customers * effective_aov * effective_frequency
    )
    revenue_per_1000_visitors = (
        overall_conversion * effective_aov * effective_frequency * 1000
    )

    # ---- Top segments by SOM contribution -------------------------
    top_segments: list[SegmentProjection] = []
    if has_cluster_data and weighted_conversion_sum > 0:
        ranked = sorted(
            entries,
            key=lambda e: e[2] * e[1],
            reverse=True,
        )
        for cid, rate, weight in ranked[:TOP_SEGMENTS_LIMIT]:
            top_segments.append(
                SegmentProjection(
                    cluster_id=cid,
                    cluster_name=_cluster_name(cid, cluster_registry),
                    population_weight=round(weight, 6),
                    conversion_rate=round(rate, 6),
                    som_share=round(
                        (weight * rate) / weighted_conversion_sum,
                        6,
                    ),
                )
            )

    # ---- Signals + narrative --------------------------------------
    signals = _build_signals(
        overall_conversion=overall_conversion,
        reachable_fraction=reachable_fraction,
        average_order_value=effective_aov,
        has_cluster_data=has_cluster_data,
    )

    if not has_cluster_data:
        narrative = (
            "No cluster breakdown in the simulation results — "
            "run a full simulation to get a market projection."
        )
    else:
        sentences = [
            (
                f"At {overall_conversion:.2%} weighted conversion, "
                f"a {tam_customers:,}-person TAM shrinks to a "
                f"{som_customers:,}-customer obtainable market "
                f"({reachable_fraction:.0%} reachable, "
                f"{effective_fraction:.0%} targeted)."
            )
        ]
        if annual_revenue > 0:
            sentences.append(
                (
                    f"At {effective_aov:.2f} AOV x "
                    f"{effective_frequency:g} purchase(s)/year, that "
                    f"projects ${annual_revenue:,.0f} annual revenue "
                    f"(${revenue_per_1000_visitors:,.0f} per 1,000 "
                    "visitors)."
                )
            )
        else:
            sentences.append(
                "Provide an average order value to project revenue."
            )
        narrative = " ".join(sentences)

    payload: dict = {
        "simulation_id": _safe_int(simulation_id),
        "project_id": _safe_int(project_id),
        "status": status or "COMPLETED",
        "overall_conversion": round(overall_conversion, 6),
        "total_agents": total_agents,
        "market_size": effective_market_size,
        "tam_customers": tam_customers,
        "sam_customers": sam_customers,
        "som_customers": som_customers,
        "reachable_fraction": round(reachable_fraction, 6),
        "average_order_value": round(effective_aov, 2),
        "purchase_frequency_per_year": round(effective_frequency, 4),
        "annual_revenue": round(annual_revenue, 2),
        "revenue_per_1000_visitors": round(
            revenue_per_1000_visitors, 2
        ),
        "product_type_detected": product_type,
        "primary_failure_domain": failure_domain,
        "signal_quality": (
            round(signal_quality, 4)
            if signal_quality is not None
            else None
        ),
        "top_segments": [s.model_dump() for s in top_segments],
        "signals": [s.model_dump() for s in signals],
        "narrative": narrative,
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "conversion_benchmark": CONVERSION_BENCHMARK,
            "reachable_min_conversion": REACHABLE_MIN_CONVERSION,
            "cluster_count": len(breakdown),
            "target_market_fraction": effective_fraction,
        },
    }
    return MarketSizingOut(**payload).model_dump()


__all__ = [
    "DEFAULT_MARKET_SIZE",
    "MIN_MARKET_SIZE",
    "MAX_MARKET_SIZE",
    "DEFAULT_TARGET_MARKET_FRACTION",
    "MIN_TARGET_MARKET_FRACTION",
    "MAX_TARGET_MARKET_FRACTION",
    "DEFAULT_AVERAGE_ORDER_VALUE",
    "DEFAULT_PURCHASE_FREQUENCY_PER_YEAR",
    "REACHABLE_MIN_CONVERSION",
    "CONVERSION_BENCHMARK",
    "CONVERSION_WATCH_THRESHOLD",
    "TOP_SEGMENTS_LIMIT",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_market_sizing",
]

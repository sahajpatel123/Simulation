"""
Pure first-customer trajectory helpers for completed simulation results.

Answers the founder follow-up to market sizing: "given my simulated
conversion, how many monthly visitors do I need, and when do I hit my
first 10 / 100 / 1,000 customers?" The digest uses the simulation's
population-weighted conversion (with the same precedence rules as
market sizing) and a linear adoption model:

``monthly_customers = monthly_visitors x weighted_conversion``

Milestone timing is ``milestone / monthly_customers`` (months + weeks),
each milestone also reports the raw visitor count required
(``ceil(milestone / conversion)``), and the adoption curve projects
cumulative customers at months 1 / 3 / 6 / 12. Cluster entries from
``cluster_breakdown`` are ranked by ``conversion_rate x
population_weight`` so the dashboard can show which segments supply the
first wave of customers.

No DB / I/O — verifiable without FastAPI or PostgreSQL. Missing or
malformed payload fields degrade conservatively (conversion 0), so a
broken legacy run can never manufacture a customer timeline.
"""
from __future__ import annotations

import json as _json
import math
from datetime import UTC, datetime
from typing import Any

from app.schemas.first_customers import (
    AdoptionCurvePoint,
    FirstCustomerMilestone,
    FirstCustomerSegment,
    FirstCustomersOut,
    FirstCustomersSignal,
)

# Founder-supplied traffic assumption (visitors per month).
DEFAULT_MONTHLY_VISITORS: int = 1000
MIN_MONTHLY_VISITORS: int = 1
MAX_MONTHLY_VISITORS: int = 10_000_000

# Milestones every founder reasons about, in order.
MILESTONES: tuple[int, ...] = (10, 100, 1000)

# Adoption-curve checkpoints (cumulative months after launch).
CURVE_MONTHS: tuple[int, ...] = (1, 3, 6, 12)

# How many clusters to surface in the first-wave ranking.
TOP_SEGMENTS_LIMIT: int = 3

# Conversion benchmark used for the traffic-light signals (same
# thresholds as the market-sizing digest so the tiles never disagree).
CONVERSION_BENCHMARK: float = 0.05
CONVERSION_WATCH_THRESHOLD: float = 0.02

# Weeks per month (365.25 / 7 / 12) for the human-readable display.
WEEKS_PER_MONTH: float = 4.348214285714286

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_visitors(value: Any) -> int:
    """Clamp the traffic assumption into its allowed range."""
    return max(
        MIN_MONTHLY_VISITORS,
        min(MAX_MONTHLY_VISITORS, _safe_int(value, DEFAULT_MONTHLY_VISITORS)),
    )


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
        rate = _safe_float(raw.get("conversion_rate"))
        if rate <= 0:
            rate = _safe_float(raw.get("conversion"))
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


def _extract_conversion(data: dict[str, Any]) -> tuple[float, str]:
    """Weighted conversion with the same precedence as market sizing."""
    raw_funnel = data.get("raw_funnel")
    if not isinstance(raw_funnel, dict):
        raw_funnel = {}
    for key in (
        "population_weighted_conversion",
        "mean_conversion_rate",
        "conversion_rate",
    ):
        rate = _safe_float(data.get(key))
        if rate > 0:
            return max(0.0, min(1.0, rate)), key
    rate = _safe_float(raw_funnel.get("conversion_rate"))
    if rate > 0:
        return max(0.0, min(1.0, rate)), "raw_funnel"
    return 0.0, "none"


def _build_milestones(
    conversion: float,
    monthly_visitors: int,
) -> list[dict[str, Any]]:
    """Compose milestone timing + visitor requirements."""
    milestones: list[dict[str, Any]] = []
    monthly_customers = monthly_visitors * conversion
    for milestone in MILESTONES:
        months: float | None = None
        weeks: float | None = None
        visitors_needed: int | None = None
        display = ""
        if monthly_customers > 0:
            months = round(milestone / monthly_customers, 2)
            weeks = round(months * WEEKS_PER_MONTH, 1)
            display = (
                f"~{months:.1f} months (~{weeks:.0f} weeks)"
            )
        if conversion > 0:
            visitors_needed = int(math.ceil(milestone / conversion))
        milestones.append(
            FirstCustomerMilestone(
                milestone=milestone,
                months=months,
                weeks=weeks,
                visitors_needed=visitors_needed,
                display=display,
            ).model_dump()
        )
    return milestones


def _build_curve(
    conversion: float,
    monthly_visitors: int,
) -> list[dict[str, Any]]:
    """Cumulative customers at the fixed curve checkpoints."""
    monthly_customers = monthly_visitors * conversion
    return [
        AdoptionCurvePoint(
            month=month,
            customers=int(round(monthly_customers * month)),
        ).model_dump()
        for month in CURVE_MONTHS
    ]


def _build_segments(
    data: dict[str, Any],
    registry: dict[str, dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Rank clusters by weighted conversion (first-adopter share)."""
    raw_breakdown = data.get("cluster_breakdown")
    breakdown: dict[str, Any] = (
        raw_breakdown if isinstance(raw_breakdown, dict) else {}
    )
    if not breakdown:
        return [], False, 0

    entries: list[tuple[str, float, float]] = []
    uniform_weight = 1.0 / max(len(breakdown), 1)
    weighted_sum = 0.0
    for cluster_id, raw_rate in breakdown.items():
        cid = str(cluster_id)
        rate = _cluster_rate(raw_rate)
        if rate <= 0:
            continue
        weight = _cluster_weight(cid, registry)
        if weight is None:
            weight = uniform_weight
        entries.append((cid, rate, weight))
        weighted_sum += weight * rate

    if not entries or weighted_sum <= 0:
        return [], bool(breakdown), len(breakdown)

    ranked = sorted(entries, key=lambda e: e[1] * e[2], reverse=True)
    segments = [
        FirstCustomerSegment(
            cluster_id=cid,
            cluster_name=_cluster_name(cid, registry),
            population_weight=round(weight, 6),
            conversion_rate=round(rate, 6),
            first_adopter_share=round(
                (weight * rate) / weighted_sum,
                6,
            ),
        ).model_dump()
        for cid, rate, weight in ranked[:TOP_SEGMENTS_LIMIT]
    ]
    return segments, True, len(breakdown)


def _build_signals(
    *,
    conversion: float,
    monthly_customers: float,
    has_cluster_data: bool,
    monthly_visitors: int,
) -> list[dict[str, Any]]:
    """Compose the traffic-light signals for the digest."""
    signals: list[dict[str, Any]] = []

    if conversion <= 0:
        signals.append(
            FirstCustomersSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_CRITICAL,
                message=(
                    "No usable conversion data in this simulation — "
                    "re-run before trusting a first-customer timeline."
                ),
            ).model_dump()
        )
    elif conversion >= CONVERSION_BENCHMARK:
        signals.append(
            FirstCustomersSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_OK,
                message=(
                    f"Conversion of {conversion:.2%} is at or above the "
                    f"{CONVERSION_BENCHMARK:.0%} benchmark."
                ),
            ).model_dump()
        )
    elif conversion >= CONVERSION_WATCH_THRESHOLD:
        signals.append(
            FirstCustomersSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_WATCH,
                message=(
                    f"Conversion of {conversion:.2%} is below the "
                    f"{CONVERSION_BENCHMARK:.0%} benchmark — validate "
                    "the offer before scaling traffic."
                ),
            ).model_dump()
        )
    else:
        signals.append(
            FirstCustomersSignal(
                key="conversion",
                label="Conversion",
                level=SIGNAL_CRITICAL,
                message=(
                    f"Conversion of {conversion:.2%} is very low — "
                    "fix core product friction before projecting "
                    "customer milestones."
                ),
            ).model_dump()
        )

    if not has_cluster_data and conversion > 0:
        signals.append(
            FirstCustomersSignal(
                key="cluster_breakdown",
                label="Cluster data",
                level=SIGNAL_WATCH,
                message=(
                    "No cluster breakdown in the results — the "
                    "first-wave ranking is unavailable and the "
                    "timeline uses the overall conversion."
                ),
            ).model_dump()
        )

    if monthly_customers <= 0:
        trajectory_level = SIGNAL_CRITICAL
        trajectory_message = (
            "No monthly customers are projected at the current "
            "conversion — the timeline is unavailable."
        )
    elif monthly_customers * 1 >= 10:
        trajectory_level = SIGNAL_OK
        trajectory_message = (
            f"At {monthly_visitors:,} monthly visitors the model "
            f"projects ~{monthly_customers:,.1f} customers/month — "
            "the first 10 customers arrive within the first month."
        )
    elif monthly_customers * 6 >= 10:
        trajectory_level = SIGNAL_WATCH
        trajectory_message = (
            f"At {monthly_visitors:,} monthly visitors the model "
            f"projects ~{monthly_customers:,.1f} customers/month — "
            "the first 10 customers take up to six months."
        )
    else:
        trajectory_level = SIGNAL_CRITICAL
        trajectory_message = (
            f"At {monthly_visitors:,} monthly visitors the model "
            f"projects ~{monthly_customers:,.1f} customers/month — "
            "the first 10 customers take more than six months; "
            "raise traffic or conversion first."
        )
    signals.append(
        FirstCustomersSignal(
            key="trajectory",
            label="Customer trajectory",
            level=trajectory_level,
            message=trajectory_message,
        ).model_dump()
    )

    return signals


def build_first_customers(
    results: Any,
    *,
    simulation_id: int = 0,
    project_id: int = 0,
    status: str = "COMPLETED",
    monthly_visitors: int = DEFAULT_MONTHLY_VISITORS,
    cluster_registry: dict[str, dict[str, Any]] | None = None,
    signal_quality: float | None = None,
) -> dict:
    """Compose the first-customer trajectory for a completed run.

    Args:
        results: simulation ``results_json`` (dict or JSON string).
            Expected keys: ``population_weighted_conversion`` /
            ``mean_conversion_rate`` / ``conversion_rate`` /
            ``raw_funnel`` and ``cluster_breakdown`` (cluster id ->
            rate or dict).
        simulation_id: persisted simulation id (forwarded verbatim).
        project_id: owning project id (forwarded verbatim).
        status: simulation status (forwarded verbatim).
        monthly_visitors: expected visitors per month; clamped into
            ``[MIN_MONTHLY_VISITORS, MAX_MONTHLY_VISITORS]``.
        cluster_registry: optional cluster id -> ``name`` +
            ``population_weight``. When missing, clusters are weighted
            uniformly.
        signal_quality: simulation signal quality (0.0 - 1.0)
            forwarded for transparency.

    Returns:
        Dict matching :class:`FirstCustomersOut`.
    """
    data = _coerce_results(results)
    visitors = _clamp_visitors(monthly_visitors)
    conversion, conversion_source = _extract_conversion(data)
    monthly_customers = visitors * conversion

    segments, has_cluster_data, cluster_count = _build_segments(
        data, cluster_registry
    )
    milestones = _build_milestones(conversion, visitors)
    curve = _build_curve(conversion, visitors)
    signals = _build_signals(
        conversion=conversion,
        monthly_customers=monthly_customers,
        has_cluster_data=has_cluster_data,
        monthly_visitors=visitors,
    )

    if conversion <= 0:
        narrative = (
            "No usable conversion data in this simulation — run a "
            "full simulation before trusting a first-customer timeline."
        )
    else:
        first_10 = milestones[0]["display"]
        first_100 = milestones[1]["display"]
        segments_note = ""
        if segments:
            names = ", ".join(s["cluster_name"] for s in segments)
            segments_note = (
                f" The strongest early segments are {names}."
            )
        narrative = (
            f"At {conversion:.2%} weighted conversion and "
            f"{visitors:,} monthly visitors, the model projects "
            f"~{monthly_customers:,.1f} customers/month: the first 10 "
            f"customers land in {first_10}, the first 100 in "
            f"{first_100}.{segments_note}"
        )

    payload: dict = {
        "simulation_id": _safe_int(simulation_id),
        "project_id": _safe_int(project_id),
        "status": status or "COMPLETED",
        "weighted_conversion_rate": round(conversion, 6),
        "monthly_visitors": visitors,
        "monthly_customers": round(monthly_customers, 2),
        "milestones": milestones,
        "adoption_curve": curve,
        "top_segments": segments,
        "signals": signals,
        "narrative": narrative,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "signal_quality": (
                round(signal_quality, 4)
                if signal_quality is not None
                else None
            ),
            "conversion_source": conversion_source,
            "conversion_benchmark": CONVERSION_BENCHMARK,
            "conversion_watch_threshold": CONVERSION_WATCH_THRESHOLD,
            "milestones": list(MILESTONES),
            "curve_months": list(CURVE_MONTHS),
            "cluster_count": cluster_count,
            "adoption_model": "linear",
        },
    }
    return FirstCustomersOut(**payload).model_dump()


__all__ = [
    "CONVERSION_BENCHMARK",
    "CONVERSION_WATCH_THRESHOLD",
    "DEFAULT_MONTHLY_VISITORS",
    "MAX_MONTHLY_VISITORS",
    "MILESTONES",
    "MIN_MONTHLY_VISITORS",
    "SIGNAL_CRITICAL",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "TOP_SEGMENTS_LIMIT",
    "WEEKS_PER_MONTH",
    "build_first_customers",
]

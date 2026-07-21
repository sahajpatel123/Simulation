"""
Pure cluster opportunity matrix for completed simulation results.

Ranks clusters by addressable conversion opportunity:

    opportunity_score = population_weight × conversion_gap × addressability

where ``conversion_gap = max(0, benchmark − conversion_rate)`` and
``addressability`` down-weights clusters that are structurally hard to
move (very low trust / extreme price sensitivity proxies via gap size).

Segments:
  * QUICK_WIN   — high weight, moderate gap (fixable near-term)
  * TRANSFORM   — high weight, large gap (strategic bet)
  * NICHE       — low weight, high conversion (protect / learn from)
  * DEPRIORITIZE — low weight, low conversion (ignore for now)

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.schemas.cluster_opportunity import (
    ClusterOpportunity,
    ClusterOpportunityMatrixOut,
    SegmentBucket,
)

# Indian SaaS/D2C soft benchmark used when scoring gaps. Clusters above
# this are treated as already "healthy" for opportunity ranking.
DEFAULT_BENCHMARK: float = 0.05

# Partial recovery of the gap that is realistically capturable.
LIFT_FRACTION: float = 0.40

# Population-weight thresholds for segment classification.
HIGH_WEIGHT: float = 0.025  # ~2.5% of population
MODERATE_GAP: float = 0.02
LARGE_GAP: float = 0.035


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
            import json as _json

            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _cluster_rate(raw: Any) -> float:
    if isinstance(raw, dict):
        return max(
            0.0,
            min(
                1.0,
                _safe_float(raw.get("conversion_rate", raw.get("conversion"))),
            ),
        )
    return max(0.0, min(1.0, _safe_float(raw)))


def _cluster_name(raw: Any, fallback: str) -> str:
    if isinstance(raw, dict):
        name = raw.get("cluster_name") or raw.get("name")
        if name:
            return str(name)
    return fallback


def _classify_segment(
    weight: float,
    conversion_rate: float,
    gap: float,
    benchmark: float,
) -> str:
    high_weight = weight >= HIGH_WEIGHT
    if high_weight and MODERATE_GAP <= gap < LARGE_GAP:
        return "QUICK_WIN"
    if high_weight and gap >= LARGE_GAP:
        return "TRANSFORM"
    if (not high_weight) and conversion_rate >= benchmark:
        return "NICHE"
    if high_weight and gap < MODERATE_GAP:
        # High weight but already near/above benchmark — protect as niche-like
        # quick retention, still labelled QUICK_WIN only if slightly below.
        return "QUICK_WIN" if gap > 0 else "NICHE"
    return "DEPRIORITIZE"


def _addressability(gap: float, conversion_rate: float) -> float:
    """
    Soften extreme gaps (near-zero converters are harder to move) and
    reward mid-gap clusters where product changes typically land.
    """
    if gap <= 0:
        return 0.0
    # Mid-gap peak around 0.04–0.06.
    peak = 0.05
    distance = abs(gap - peak)
    base = max(0.35, 1.0 - distance * 6.0)
    # Near-zero CR is structurally harder.
    if conversion_rate < 0.005:
        base *= 0.70
    return round(max(0.25, min(1.0, base)), 4)


def _recommended_action(
    segment: str,
    cluster_id: str,
    trigger: str | None,
    drop_state: str | None,
) -> str:
    focus = trigger or drop_state or "core product friction"
    if segment == "QUICK_WIN":
        return (
            f"Prioritise near-term fixes for '{cluster_id}' — "
            f"moderate gap, high reach. Focus: {focus}."
        )
    if segment == "TRANSFORM":
        return (
            f"Strategic redesign for '{cluster_id}' — large conversion gap "
            f"on a high-weight segment. Focus: {focus}."
        )
    if segment == "NICHE":
        return (
            f"Protect and learn from '{cluster_id}' — already converting "
            "well; mine messaging/positioning for broader segments."
        )
    return (
        f"Deprioritise '{cluster_id}' for now — low population weight "
        f"and weak conversion. Revisit after core segments improve."
    )


def _build_segment_breakdown(
    opportunities: list[ClusterOpportunity],
) -> list[SegmentBucket]:
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "opp": 0.0, "weight": 0.0, "cr_sum": 0.0}
    )
    for op in opportunities:
        b = buckets[op.segment]
        b["count"] += 1
        b["opp"] += op.opportunity_score
        b["weight"] += op.population_weight
        b["cr_sum"] += op.conversion_rate

    order = ["QUICK_WIN", "TRANSFORM", "NICHE", "DEPRIORITIZE"]
    out: list[SegmentBucket] = []
    for seg in order:
        if seg not in buckets:
            continue
        b = buckets[seg]
        n = max(1, int(b["count"]))
        out.append(
            SegmentBucket(
                segment=seg,
                cluster_count=int(b["count"]),
                total_opportunity=round(b["opp"], 6),
                total_population_weight=round(b["weight"], 6),
                mean_conversion=round(b["cr_sum"] / n, 4),
            )
        )
    return out


def _focus_recommendations(
    opportunities: list[ClusterOpportunity],
    addressable_lift: float,
    overall: float,
) -> list[str]:
    tips: list[str] = []
    quick = [o for o in opportunities if o.segment == "QUICK_WIN"]
    transform = [o for o in opportunities if o.segment == "TRANSFORM"]
    niche = [o for o in opportunities if o.segment == "NICHE"]

    if quick:
        top = quick[0]
        tips.append(
            f"Ship a quick win on '{top.cluster_id}' "
            f"(est. lift +{top.estimated_lift:.1%})."
        )
    if transform:
        top = transform[0]
        tips.append(
            f"Schedule a strategic bet on '{top.cluster_id}' "
            f"(gap {top.conversion_gap:.1%}, weight {top.population_weight:.1%})."
        )
    if niche:
        tips.append(
            f"Reuse messaging that works for '{niche[0].cluster_id}' "
            f"(CR {niche[0].conversion_rate:.1%}) across weaker segments."
        )
    if addressable_lift > 0:
        tips.append(
            f"Top-ranked opportunities could raise conversion from "
            f"{overall:.1%} toward ~{overall + addressable_lift:.1%} "
            f"(+{addressable_lift:.1%} addressable)."
        )
    if not tips:
        tips.append(
            "No high-weight conversion gaps detected — maintain current "
            "targeting and monitor simulation trend for regressions."
        )
    return tips[:5]


def build_cluster_opportunity_matrix(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    cluster_summaries: list[dict[str, Any]] | None = None,
    cluster_registry: dict[str, dict[str, Any]] | None = None,
    benchmark: float = DEFAULT_BENCHMARK,
    limit: int = 52,
) -> ClusterOpportunityMatrixOut:
    """
    Build the opportunity matrix from persisted results (+ optional summaries).

    Safe on empty / malformed payloads — returns a zero-state matrix rather
    than raising so the API can always respond 200 for completed sims.
    """
    data = _coerce_results(results)
    overall = max(
        0.0,
        min(
            1.0,
            _safe_float(
                data.get("population_weighted_conversion", data.get("conversion_rate"))
            ),
        ),
    )
    total_agents = _safe_int(data.get("total_agents"))
    benchmark = max(0.01, min(0.5, _safe_float(benchmark, DEFAULT_BENCHMARK)))
    limit = max(1, min(int(limit) if isinstance(limit, int) else 52, 52))

    breakdown = data.get("cluster_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}

    summary_by_id: dict[str, dict[str, Any]] = {}
    if cluster_summaries:
        for row in cluster_summaries:
            if isinstance(row, dict) and row.get("cluster_id"):
                summary_by_id[str(row["cluster_id"])] = row

    total_assigned = sum(
        max(0, _safe_int(s.get("agents_assigned"))) for s in summary_by_id.values()
    )

    registry = cluster_registry or {}
    opportunities: list[ClusterOpportunity] = []

    # Union of breakdown keys + summary keys so orphan summaries still appear.
    cluster_ids = {str(k) for k in breakdown.keys()} | set(summary_by_id.keys())

    for cid in cluster_ids:
        raw = breakdown.get(cid)
        if raw is None:
            for k, v in breakdown.items():
                if str(k) == cid:
                    raw = v
                    break
        summary = summary_by_id.get(cid, {})
        if raw is None and summary:
            cr = max(0.0, min(1.0, _safe_float(summary.get("conversion_rate"))))
        else:
            cr = _cluster_rate(raw)

        agents_assigned = _safe_int(summary.get("agents_assigned")) or None
        if total_assigned > 0 and agents_assigned:
            weight = agents_assigned / total_assigned
        else:
            reg_w = registry.get(cid, {}).get("population_weight")
            if reg_w is not None:
                weight = max(0.0, _safe_float(reg_w))
            elif cluster_ids:
                weight = 1.0 / len(cluster_ids)
            else:
                weight = 0.0

        gap = max(0.0, benchmark - cr)
        addr = _addressability(gap, cr)
        score = round(weight * gap * addr, 6)
        est_lift = round(weight * gap * LIFT_FRACTION, 6)
        segment = _classify_segment(weight, cr, gap, benchmark)
        trigger = (
            str(summary["primary_drop_trigger"])
            if summary.get("primary_drop_trigger")
            else None
        )
        drop_state = (
            str(summary["mean_drop_state"]) if summary.get("mean_drop_state") else None
        )
        name = _cluster_name(raw, str(registry.get(cid, {}).get("name", cid)))

        opportunities.append(
            ClusterOpportunity(
                cluster_id=cid,
                cluster_name=name,
                population_weight=round(weight, 6),
                conversion_rate=round(cr, 4),
                conversion_gap=round(gap, 4),
                opportunity_score=score,
                segment=segment,
                estimated_lift=est_lift,
                primary_drop_trigger=trigger,
                mean_drop_state=drop_state,
                agents_assigned=agents_assigned,
                agents_converted=(
                    _safe_int(summary.get("agents_converted"))
                    if summary.get("agents_converted") is not None
                    else None
                ),
                recommended_action=_recommended_action(
                    segment, cid, trigger, drop_state
                ),
            )
        )

    opportunities.sort(
        key=lambda o: (-o.opportunity_score, -o.population_weight, o.cluster_id)
    )
    opportunities = opportunities[:limit]

    # Addressable lift = sum of estimated lifts for QUICK_WIN + TRANSFORM,
    # capped so we never promise more than (benchmark - overall) * 1.5.
    focus_ops = [
        o for o in opportunities if o.segment in {"QUICK_WIN", "TRANSFORM"}
    ]
    raw_lift = sum(o.estimated_lift for o in focus_ops[:5])
    cap = max(0.0, (benchmark - overall) * 1.5) if overall < benchmark else raw_lift
    # Always allow at least the top focus lifts when overall already >= benchmark.
    addressable = round(min(raw_lift, max(cap, raw_lift if overall >= benchmark else cap), 0.25), 4)

    top_cluster = opportunities[0].cluster_id if opportunities else None
    segments = _build_segment_breakdown(opportunities)
    tips = _focus_recommendations(opportunities, addressable, overall)

    return ClusterOpportunityMatrixOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        overall_conversion=round(overall, 4),
        total_agents=total_agents,
        addressable_lift=addressable,
        top_opportunity_cluster=top_cluster,
        opportunities=opportunities,
        segment_breakdown=segments,
        focus_recommendations=tips,
        product_type_detected=str(data.get("product_type_detected") or ""),
        primary_failure_domain=str(data.get("primary_failure_domain") or "unknown"),
        signal_quality=signal_quality,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "benchmark": benchmark,
            "lift_fraction": LIFT_FRACTION,
            "cluster_summaries_used": bool(cluster_summaries),
            "cluster_count": len(opportunities),
        },
    )


__all__ = [
    "DEFAULT_BENCHMARK",
    "LIFT_FRACTION",
    "HIGH_WEIGHT",
    "build_cluster_opportunity_matrix",
]

"""
Pure demand-concentration analysis for completed simulation results.

Answers the founder's "how fragile is my projected demand?" question.
When projected conversions are spread across 52 consumer clusters, a
small set of segments often carries most of the demand; if that
concentration goes unnoticed, a single cohort's failure can sink the
whole launch. This module measures it and turns it into a verdict.

For each cluster, projected demand = population_weight × conversion_rate.
Each cluster's demand share = its projected demand ÷ total projected
demand. Concentration is then summarised with:

* ``hhi`` — Herfindahl-Hirschman Index (sum of squared demand shares;
  1.0 means one cluster owns all demand).
* ``normalized_hhi`` — HHI scaled by the perfectly-diversified baseline
  for the observed cluster count, so 0.0 = evenly spread and 1.0 =
  single-segment monopoly regardless of how many clusters exist.
* ``effective_segments`` — 1 / HHI (capped), the number of equally
  sized segments that would produce the same concentration.
* ``top_1_share`` / ``top_3_share`` / ``top_5_share`` — cumulative
  demand share of the top clusters.
* ``verdict`` — DIVERSIFIED / MODERATE / CONCENTRATED /
  INSUFFICIENT_DATA, plus ``fragility_flags`` and
  ``recommendations`` for the dashboard tile.

No DB / I/O — verifiable without FastAPI or PostgreSQL. The route
layer supplies ``results`` plus optional ``cluster_registry``
(id -> name + population_weight) and ``cluster_summaries``
(agents_assigned per cluster) so weights fall back gracefully when
any source is missing.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from app.schemas.market_concentration import (
    ClusterDemandShare,
    MarketConcentrationOut,
)

# Verdict thresholds on the *normalized* HHI (0..1). Normalizing makes
# the thresholds meaningful for any cluster count: 52 uniform clusters
# give 0.0 (diversified) while a single 60%-share segment lands above
# the concentrated bar.
CONCENTRATED_NHHI: float = 0.30
MODERATE_NHHI: float = 0.10

# Top-N demand-share thresholds that trigger fragility flags. Each is
# combined with a "fair share" multiplier so a small cluster count does
# not produce false alarms: a cluster must hold a large absolute share
# *and* be clearly above its fair share (1/N) to be a dependency risk.
SINGLE_SEGMENT_MAX_SHARE: float = 0.30
SINGLE_SEGMENT_FAIR_SHARE_MULTIPLIER: float = 2.0
TOP3_MAX_SHARE: float = 0.60
TOP3_FAIR_SHARE_MULTIPLIER: float = 1.5

VERDICT_DIVERSIFIED: str = "DIVERSIFIED"
VERDICT_MODERATE: str = "MODERATE"
VERDICT_CONCENTRATED: str = "CONCENTRATED"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

FLAG_SINGLE_SEGMENT: str = "SINGLE_SEGMENT_DEPENDENCY"
FLAG_TOP_HEAVY: str = "TOP_HEAVY"
FLAG_HIGH_CONCENTRATION: str = "HIGH_CONCENTRATION"


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


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


def _cluster_rate(raw: Any) -> float:
    """Extract a clamped conversion rate from a cluster entry."""
    if raw is None:
        return 0.0
    if isinstance(raw, dict):
        rate = raw.get("conversion_rate", raw.get("conversion"))
    else:
        rate = raw
    return max(0.0, min(1.0, _safe_float(rate)))


def _cluster_weight(
    cluster_id: str,
    registry: dict[str, dict[str, Any]],
    summary_by_id: dict[str, dict[str, Any]],
    total_assigned: int,
    total_clusters: int,
) -> tuple[float, str]:
    """Resolve a cluster's demand weight with graceful fallbacks.

    Returns ``(weight, source)`` where ``source`` is one of
    ``"registry"``, ``"cluster_run_summaries"``, or ``"uniform"`` so
    the caller can report honestly which data actually drove the
    concentration read.
    """
    reg = registry.get(cluster_id) or {}
    reg_weight = _safe_float(reg.get("population_weight"))
    if reg_weight > 0.0:
        return reg_weight, "registry"
    summary = summary_by_id.get(cluster_id) or {}
    assigned = _safe_int(summary.get("agents_assigned"))
    if total_assigned > 0 and assigned > 0:
        return assigned / total_assigned, "cluster_run_summaries"
    if total_clusters > 0:
        return 1.0 / total_clusters, "uniform"
    return 0.0, "uniform"


def _recommendations(
    verdict: str,
    flags: list[str],
    items: list[ClusterDemandShare],
    top_3_share: float,
    effective_segments: float,
) -> list[str]:
    """Human-readable, founder-facing guidance from the concentration read."""
    recs: list[str] = []
    top = items[0] if items else None
    if FLAG_SINGLE_SEGMENT in flags and top is not None:
        recs.append(
            f"{top.cluster_name} drives {top.demand_share * 100:.0f}% of projected "
            "demand — plan a segment-diversification GTM so one cohort cannot sink "
            "the business."
        )
    if FLAG_TOP_HEAVY in flags:
        recs.append(
            f"The top 3 segments drive {top_3_share * 100:.0f}% of projected demand — "
            "monitor retention and pricing changes in these clusters first."
        )
    if FLAG_HIGH_CONCENTRATION in flags:
        recs.append(
            "Demand is highly concentrated — invest in adjacent segments or a second "
            "use case to spread conversion risk."
        )
    if verdict == VERDICT_DIVERSIFIED and effective_segments >= 1:
        recs.append(
            f"Demand is well spread across ~{effective_segments:.0f} effective "
            "segments — concentration risk is low; keep the strongest segments as "
            "your beachhead."
        )
    if not recs:
        recs.append(
            "Demand concentration is moderate — watch the top segments and re-run "
            "after any pricing or targeting change."
        )
    return recs


def build_market_concentration(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    cluster_summaries: list[dict[str, Any]] | None = None,
    cluster_registry: dict[str, dict[str, Any]] | None = None,
) -> MarketConcentrationOut:
    """
    Build the demand-concentration read from persisted results.

    Safe on empty / malformed payloads — returns a zero-state verdict
    rather than raising so the API can always respond 200 for completed
    simulations.
    """
    data = _coerce_results(results)
    breakdown = data.get("cluster_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}

    summary_by_id: dict[str, dict[str, Any]] = {}
    if cluster_summaries:
        for row in cluster_summaries:
            if isinstance(row, dict) and row.get("cluster_id"):
                summary_by_id[str(row["cluster_id"])] = row
    total_assigned = sum(
        max(0, _safe_int(s.get("agents_assigned")))
        for s in summary_by_id.values()
    )

    registry = cluster_registry or {}
    cluster_ids = [str(k) for k in breakdown.keys()]
    total_clusters = len(cluster_ids)

    # (cluster_id, weight, conversion_rate) for every cluster that
    # actually contributes demand; zero-conversion clusters are
    # excluded because they hold no share of projected customers.
    weighted: list[tuple[str, float, float]] = []
    weight_sources: set[str] = set()
    for cid in cluster_ids:
        rate = _cluster_rate(breakdown.get(cid))
        if rate <= 0.0:
            continue
        weight, source = _cluster_weight(
            cid, registry, summary_by_id, total_assigned, total_clusters
        )
        if weight <= 0.0:
            continue
        weighted.append((cid, weight, rate))
        weight_sources.add(source)

    total_weight = sum(w for _, w, _ in weighted)
    total_demand = sum(w * r for _, w, r in weighted)
    if not weighted or total_weight <= 0.0 or total_demand <= 0.0:
        return MarketConcentrationOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            signal_quality=signal_quality,
            verdict=VERDICT_INSUFFICIENT,
            total_clusters=total_clusters,
            clusters_with_demand=0,
            recommendations=[
                "No measurable cluster demand in these results — run a completed "
                "simulation to get a concentration read."
            ],
        )

    items: list[ClusterDemandShare] = []
    running = 0.0
    for cid, weight, rate in sorted(
        weighted, key=lambda item: item[1] * item[2], reverse=True
    ):
        share = (weight * rate) / total_demand
        running += share
        items.append(
            ClusterDemandShare(
                cluster_id=cid,
                cluster_name=str(registry.get(cid, {}).get("name") or cid),
                population_weight=round(weight, 6),
                conversion_rate=round(rate, 4),
                demand_share=round(share, 6),
                cumulative_share=round(running, 6),
            )
        )

    hhi = sum(item.demand_share ** 2 for item in items)
    diversified_baseline = 1.0 / len(items)
    if len(items) == 1:
        # A single segment owning all demand is a perfect monopoly.
        # The usual normalisation divides by ``1 - baseline`` which is
        # zero here, so report maximum concentration explicitly.
        normalized_hhi = 1.0
    elif hhi > diversified_baseline:
        normalized_hhi = (hhi - diversified_baseline) / (
            1.0 - diversified_baseline
        )
    else:
        normalized_hhi = 0.0
    hhi = round(hhi, 6)
    normalized_hhi = round(max(0.0, min(1.0, normalized_hhi)), 6)
    effective_segments = (
        round(min(float(len(items)), 1.0 / hhi), 2) if hhi > 0.0 else 0.0
    )

    top_1 = items[0].demand_share
    top_3 = sum(item.demand_share for item in items[:3])
    top_5 = sum(item.demand_share for item in items[:5])

    if normalized_hhi >= CONCENTRATED_NHHI:
        verdict = VERDICT_CONCENTRATED
    elif normalized_hhi >= MODERATE_NHHI:
        verdict = VERDICT_MODERATE
    else:
        verdict = VERDICT_DIVERSIFIED

    fair_share = 1.0 / len(items)
    flags: list[str] = []
    # Cap the fair-share term at 1.0: with a single segment the
    # multiplier would push the threshold above 100% and the most
    # concentrated market possible would never flag.
    single_segment_threshold = min(
        1.0,
        max(
            SINGLE_SEGMENT_MAX_SHARE,
            SINGLE_SEGMENT_FAIR_SHARE_MULTIPLIER * fair_share,
        ),
    )
    if top_1 >= single_segment_threshold:
        flags.append(FLAG_SINGLE_SEGMENT)
    if top_3 >= max(
        TOP3_MAX_SHARE,
        TOP3_FAIR_SHARE_MULTIPLIER * 3 * fair_share,
    ):
        flags.append(FLAG_TOP_HEAVY)
    if normalized_hhi >= CONCENTRATED_NHHI:
        flags.append(FLAG_HIGH_CONCENTRATION)

    return MarketConcentrationOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        signal_quality=signal_quality,
        total_conversion_rate=round(total_demand / total_weight, 4),
        hhi=hhi,
        normalized_hhi=normalized_hhi,
        effective_segments=effective_segments,
        verdict=verdict,
        top_1_share=round(top_1, 6),
        top_3_share=round(top_3, 6),
        top_5_share=round(top_5, 6),
        top_cluster_id=items[0].cluster_id,
        top_cluster_name=items[0].cluster_name,
        total_clusters=total_clusters,
        clusters_with_demand=len(items),
        fragility_flags=flags,
        recommendations=_recommendations(
            verdict, flags, items, top_3, effective_segments
        ),
        segment_shares=items,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cluster_summaries_used": bool(cluster_summaries),
            "cluster_count": len(items),
            "demand_weighting": (
                "registry"
                if "registry" in weight_sources
                else "cluster_run_summaries"
                if "cluster_run_summaries" in weight_sources
                else "uniform"
            ),
        },
    )


__all__ = [
    "CONCENTRATED_NHHI",
    "MODERATE_NHHI",
    "SINGLE_SEGMENT_MAX_SHARE",
    "SINGLE_SEGMENT_FAIR_SHARE_MULTIPLIER",
    "TOP3_MAX_SHARE",
    "TOP3_FAIR_SHARE_MULTIPLIER",
    "VERDICT_DIVERSIFIED",
    "VERDICT_MODERATE",
    "VERDICT_CONCENTRATED",
    "VERDICT_INSUFFICIENT",
    "FLAG_SINGLE_SEGMENT",
    "FLAG_TOP_HEAVY",
    "FLAG_HIGH_CONCENTRATION",
    "build_market_concentration",
]

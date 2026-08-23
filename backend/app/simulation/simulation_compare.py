"""
Diff two completed simulations' results.

Founders re-run a simulation after changing assumptions, price, or
positioning; the comparison endpoint turns the second wall of numbers
into a diff: headline conversion movement, per-stage drop-off changes,
and the consumer clusters that drove the shift.

The builder is pure — it takes both ``results_json`` payloads plus the
two runs' signal/confidence scalars and returns a
``SimulationRunDiffOut``. Missing keys degrade to ``None`` fields so
older payloads (or hardware-shaped ones) compare gracefully instead of
crashing.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.simulation_compare import (
    DIRECTION_LITERAL,
    FLAT_THRESHOLD_RATE_POINTS,
    VERDICT_LITERAL,
    ClusterDelta,
    HeadlineComparison,
    SimulationRunDiffOut,
    StageDelta,
)

MAX_CLUSTER_ROWS: int = 12


def _f(value: object) -> float | None:
    """Best-effort float coercion; anything unconvertible becomes None."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _verdict(delta_pp: float) -> VERDICT_LITERAL:
    if abs(delta_pp) < FLAT_THRESHOLD_RATE_POINTS * 100.0:
        return "FLAT"
    return "IMPROVED" if delta_pp > 0 else "REGRESSED"


def _direction(delta_pp: float) -> DIRECTION_LITERAL:
    if abs(delta_pp) < FLAT_THRESHOLD_RATE_POINTS * 100.0:
        return "UNCHANGED"
    return "IMPROVED" if delta_pp > 0 else "WORSENED"


def _stage_map(results: dict) -> dict[str, float]:
    stages: dict[str, float] = {}
    for raw in results.get("stage_aggregations") or []:
        row = raw if isinstance(raw, dict) else {}
        state = str(row.get("state") or "").strip()
        drop = _f(row.get("mean_drop_off_rate"))
        if state and drop is not None:
            stages[state] = drop
    return stages


def build_simulation_comparison(
    *,
    simulation_id: int,
    baseline_id: int,
    current_results: dict,
    baseline_results: dict,
    current_signal: float | None = None,
    baseline_signal: float | None = None,
    project_id: int | None = None,
) -> SimulationRunDiffOut:
    """
    Build a founder-facing diff between a run and its baseline.

    The headline compares ``mean_conversion_rate`` in percentage points;
    stage rows match on funnel-state name; cluster rows union both runs'
    ``cluster_breakdown`` maps and sort by absolute impact, largest first.
    """
    conv_before = _f(baseline_results.get("mean_conversion_rate")) or 0.0
    conv_after = _f(current_results.get("mean_conversion_rate")) or 0.0
    delta_pp = round((conv_after - conv_before) * 100.0, 4)
    delta_pct = (
        round((conv_after - conv_before) / conv_before, 6)
        if conv_before > 0
        else None
    )

    conf_before = _f(baseline_results.get("confidence_score"))
    conf_after = _f(current_results.get("confidence_score"))

    worst_before = str(baseline_results.get("worst_drop_off_stage") or "")
    worst_after = str(current_results.get("worst_drop_off_stage") or "")

    headline = HeadlineComparison(
        conversion_before=round(conv_before, 6),
        conversion_after=round(conv_after, 6),
        conversion_delta_pp=delta_pp,
        conversion_delta_pct=delta_pct,
        verdict=_verdict(delta_pp),
        revenue_before=round(_f(baseline_results.get("mean_revenue")) or 0.0, 2),
        revenue_after=round(_f(current_results.get("mean_revenue")) or 0.0, 2),
        confidence_before=conf_before,
        confidence_after=conf_after,
        signal_quality_before=(
            round(baseline_signal, 4) if baseline_signal is not None else None
        ),
        signal_quality_after=(
            round(current_signal, 4) if current_signal is not None else None
        ),
        worst_drop_off_stage_before=worst_before,
        worst_drop_off_stage_after=worst_after,
        worst_stage_changed=(worst_before != worst_after),
    )

    # Stage deltas: union of states seen in either run.
    before_stages = _stage_map(baseline_results)
    after_stages = _stage_map(current_results)
    stage_deltas = [
        StageDelta(
            state=state,
            drop_off_before=(
                round(before_stages[state], 6) if state in before_stages else None
            ),
            drop_off_after=(
                round(after_stages[state], 6) if state in after_stages else None
            ),
            drop_off_delta_pp=round(
                ((after_stages.get(state) or 0.0) - (before_stages.get(state) or 0.0))
                * 100.0,
                4,
            ),
        )
        for state in sorted(set(before_stages) | set(after_stages))
    ]

    # Cluster deltas: union of both breakdowns, sorted by absolute impact.
    before_clusters = baseline_results.get("cluster_breakdown") or {}
    after_clusters = current_results.get("cluster_breakdown") or {}
    cluster_rows: list[ClusterDelta] = []
    for cid in sorted(set(before_clusters) | set(after_clusters)):
        c_before = (
            _f(before_clusters.get(cid)) if isinstance(before_clusters, dict) else None
        )
        c_after = (
            _f(after_clusters.get(cid)) if isinstance(after_clusters, dict) else None
        )
        c_delta_pp = round(((c_after or 0.0) - (c_before or 0.0)) * 100.0, 4)
        cluster_rows.append(
            ClusterDelta(
                cluster_id=str(cid),
                conversion_before=(
                    round(c_before, 6) if c_before is not None else None
                ),
                conversion_after=(
                    round(c_after, 6) if c_after is not None else None
                ),
                conversion_delta_pp=c_delta_pp,
                direction=_direction(c_delta_pp),
            )
        )
    cluster_rows.sort(key=lambda r: -abs(r.conversion_delta_pp))

    clusters_shown = cluster_rows[:MAX_CLUSTER_ROWS]
    improved = sum(1 for r in cluster_rows if r.direction == "IMPROVED")
    worsened = sum(1 for r in cluster_rows if r.direction == "WORSENED")
    mover = clusters_shown[0] if clusters_shown else None

    sign = "+" if delta_pp >= 0 else ""
    narrative_parts = [
        f"Compared with simulation {baseline_id}: predicted conversion moved "
        f"{headline.conversion_before:.2%} → {headline.conversion_after:.2%} "
        f"({sign}{delta_pp:.2f}pp, {headline.verdict.lower()})."
    ]
    if improved or worsened:
        narrative_parts.append(
            f"{improved} cluster(s) improved and {worsened} worsened."
        )
    if mover and mover.direction != "UNCHANGED":
        arrow = "+" if mover.conversion_delta_pp >= 0 else ""
        narrative_parts.append(
            f"Biggest mover '{mover.cluster_id}' "
            f"({arrow}{mover.conversion_delta_pp:.2f}pp)."
        )
    if headline.worst_stage_changed:
        narrative_parts.append(
            f"Weakest stage shifted from '{worst_before}' to '{worst_after}'."
        )

    return SimulationRunDiffOut(
        simulation_id=simulation_id,
        baseline_id=baseline_id,
        project_id=project_id,
        headline=headline,
        stage_deltas=stage_deltas,
        cluster_deltas=clusters_shown,
        clusters_improved=improved,
        clusters_worsened=worsened,
        biggest_mover=mover,
        narrative=" ".join(narrative_parts),
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "simulation_compare_v1",
            "flat_threshold_pp": FLAT_THRESHOLD_RATE_POINTS * 100.0,
            "clusters_shown": min(len(cluster_rows), MAX_CLUSTER_ROWS),
            "clusters_total": len(cluster_rows),
            "headline_key": "mean_conversion_rate",
        },
    )


__all__ = [
    "MAX_CLUSTER_ROWS",
    "build_simulation_comparison",
]

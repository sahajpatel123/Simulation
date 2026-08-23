from __future__ import annotations

import math
from typing import Any

# Thresholds for cohort drift severity
DRIFT_THRESHOLD_LOW = 0.02    # < 2% conversion delta is negligible
DRIFT_THRESHOLD_MED = 0.05    # 2% - 5% conversion delta is moderate
# > 5% conversion delta is high severity

SIGNAL_OK = "ok"
SIGNAL_WATCH = "watch"
SIGNAL_CRITICAL = "critical"


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or f == float("inf") or f == float("-inf"):
            return default
        return f
    except (ValueError, TypeError):
        return default


def compute_cluster_cohort_drift(
    baseline_results: dict[str, Any] | None,
    latest_results: dict[str, Any] | None,
    max_top: int = 5,
) -> dict[str, Any]:
    """Analyze conversion drift across consumer clusters between two simulation runs.

    Compares baseline and latest simulation results per cluster, calculating
    absolute and relative conversion rate shifts, identifying top drifting cohorts,
    and classifying overall portfolio stability.

    Args:
        baseline_results: Simulation results JSON dict for baseline run.
        latest_results: Simulation results JSON dict for comparison run.
        max_top: Maximum number of top drifting clusters to highlight.

    Returns:
        Dict containing drift statistics, cluster breakdowns, overall score,
        stability classification, narrative, and key signals.
    """
    baseline_results = baseline_results or {}
    latest_results = latest_results or {}

    base_breakdown = baseline_results.get("cluster_breakdown") or {}
    latest_breakdown = latest_results.get("cluster_breakdown") or {}

    if not isinstance(base_breakdown, dict):
        base_breakdown = {}
    if not isinstance(latest_breakdown, dict):
        latest_breakdown = {}

    all_cluster_ids = sorted(
        set(str(k) for k in base_breakdown.keys())
        | set(str(k) for k in latest_breakdown.keys())
    )

    drift_by_cluster: dict[str, dict[str, Any]] = {}
    drifting_list: list[dict[str, Any]] = []

    total_abs_drift = 0.0
    clusters_analyzed = 0

    for cid in all_cluster_ids:
        base_data = base_breakdown.get(cid) or {}
        latest_data = latest_breakdown.get(cid) or {}

        if not isinstance(base_data, dict):
            base_data = {}
        if not isinstance(latest_data, dict):
            latest_data = {}

        base_conv = _safe_float(base_data.get("conversion_rate"))
        latest_conv = _safe_float(latest_data.get("conversion_rate"))

        abs_drift = latest_conv - base_conv
        mag_drift = abs(abs_drift)

        if base_conv > 0:
            rel_drift_pct = (abs_drift / base_conv) * 100.0
        else:
            rel_drift_pct = 100.0 if latest_conv > 0 else 0.0

        if abs_drift > 0.001:
            direction = "EXPANDING"
        elif abs_drift < -0.001:
            direction = "CONTRACTING"
        else:
            direction = "NEUTRAL"

        if mag_drift >= DRIFT_THRESHOLD_MED:
            severity = SIGNAL_CRITICAL if abs_drift < 0 else SIGNAL_WATCH
        elif mag_drift >= DRIFT_THRESHOLD_LOW:
            severity = SIGNAL_WATCH
        else:
            severity = SIGNAL_OK

        cluster_info = {
            "cluster_id": cid,
            "baseline_conversion": round(base_conv, 4),
            "latest_conversion": round(latest_conv, 4),
            "absolute_drift": round(abs_drift, 4),
            "relative_drift_pct": round(rel_drift_pct, 2),
            "drift_magnitude": round(mag_drift, 4),
            "direction": direction,
            "severity": severity,
        }

        drift_by_cluster[cid] = cluster_info
        drifting_list.append(cluster_info)
        total_abs_drift += mag_drift
        clusters_analyzed += 1

    # Sort clusters by magnitude of drift descending
    drifting_list.sort(key=lambda x: x["drift_magnitude"], reverse=True)
    top_drifting_clusters = drifting_list[:max_top]

    avg_drift = (total_abs_drift / clusters_analyzed) if clusters_analyzed > 0 else 0.0
    overall_drift_score = min(100.0, round(avg_drift * 500.0, 2))

    if overall_drift_score >= 25.0:
        stability = "HIGH_DRIFT"
        overall_severity = SIGNAL_CRITICAL
    elif overall_drift_score >= 10.0:
        stability = "MODERATE_DRIFT"
        overall_severity = SIGNAL_WATCH
    else:
        stability = "STABLE"
        overall_severity = SIGNAL_OK

    # Generate narrative
    sentences: list[str] = []
    if clusters_analyzed == 0:
        sentences.append("No cluster breakdown data available to analyze cohort drift.")
    else:
        sentences.append(
            f"Analyzed conversion drift across {clusters_analyzed} cluster cohort(s). "
            f"Overall cohort stability is classified as {stability} (drift score: {overall_drift_score}/100)."
        )
        if top_drifting_clusters:
            top1 = top_drifting_clusters[0]
            sentences.append(
                f"Highest volatility observed in cluster '{top1['cluster_id']}' with a "
                f"{top1['absolute_drift']:+.2%} conversion shift ({top1['direction'].lower()})."
            )

    narrative = " ".join(sentences)

    key_signals: list[dict[str, Any]] = [
        {
            "label": "cohort_stability",
            "value": stability,
            "severity": overall_severity,
            "display": f"Cohort Stability: {stability}",
        },
        {
            "label": "drift_score",
            "value": overall_drift_score,
            "severity": overall_severity,
            "display": f"Cohort Drift Score: {overall_drift_score}/100",
        },
    ]

    return {
        "clusters_analyzed": clusters_analyzed,
        "overall_drift_score": overall_drift_score,
        "stability_classification": stability,
        "drift_by_cluster": drift_by_cluster,
        "top_drifting_clusters": top_drifting_clusters,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "compute_cluster_cohort_drift",
    "DRIFT_THRESHOLD_LOW",
    "DRIFT_THRESHOLD_MED",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
]

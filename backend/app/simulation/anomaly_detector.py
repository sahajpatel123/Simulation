from __future__ import annotations

import math
from typing import Any

ANOMALY_SCORE_CAP = 100.0

SIGNAL_OK = "ok"
SIGNAL_WATCH = "watch"
SIGNAL_CRITICAL = "critical"

DEFAULT_STAGES = ["ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE"]


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if f != f or f == float("inf") or f == float("-inf"):
            return default
        return f
    except (ValueError, TypeError):
        return default


def detect_simulation_anomalies(
    results_json: dict[str, Any] | None,
    outlier_z_threshold: float = 2.0,
    dropoff_spike_threshold: float = 0.75,
) -> dict[str, Any]:
    """Detect statistical anomalies, stage drop-off spikes, and cluster outliers in simulation results.

    Args:
        results_json: Simulation results JSON dictionary containing stage_conversions,
            cluster_breakdown, architect_outputs, or funnel_graph.
        outlier_z_threshold: Z-score cutoff for identifying cluster conversion outliers.
        dropoff_spike_threshold: Drop-off fraction (0.0 - 1.0) above which a stage is flagged as a spike.

    Returns:
        Dict containing anomaly_score, status, detected_anomalies list, stage_spikes,
        cluster_outliers, recommendations, narrative, and key_signals.
    """
    results_json = results_json or {}

    anomalies: list[dict[str, Any]] = []
    stage_spikes: list[dict[str, Any]] = []
    cluster_outliers: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    anomaly_penalty = 0.0

    # 1. Funnel Stage Drop-off Spikes (supports string & dict stage_conversions)
    stage_conversions = results_json.get("stage_conversions") or {}
    if not isinstance(stage_conversions, dict):
        stage_conversions = {}

    # Case-insensitive normalized stage lookups
    normalized_conversions: dict[str, float] = {}
    for k, v in stage_conversions.items():
        if isinstance(k, str):
            normalized_conversions[k.upper()] = _safe_float(v)

    # Determine applicable stages sequence
    present_stages = [s for s in DEFAULT_STAGES if s in normalized_conversions]
    stages_to_evaluate = present_stages if len(present_stages) >= 2 else DEFAULT_STAGES

    for i in range(len(stages_to_evaluate) - 1):
        curr_stage = stages_to_evaluate[i]
        next_stage = stages_to_evaluate[i + 1]

        curr_val = normalized_conversions.get(curr_stage, 0.0)
        next_val = normalized_conversions.get(next_stage, 0.0)

        if curr_val > 0:
            dropoff_rate = max(0.0, (curr_val - next_val) / curr_val)
            if dropoff_rate >= dropoff_spike_threshold:
                severity = SIGNAL_CRITICAL if dropoff_rate >= 0.85 else SIGNAL_WATCH
                spike_item = {
                    "stage_from": curr_stage,
                    "stage_to": next_stage,
                    "dropoff_rate": round(dropoff_rate, 4),
                    "curr_conversion": round(curr_val, 4),
                    "next_conversion": round(next_val, 4),
                    "severity": severity,
                }
                stage_spikes.append(spike_item)
                anomalies.append({
                    "type": "STAGE_DROPOFF_SPIKE",
                    "description": f"Severe drop-off of {dropoff_rate:.1%} between {curr_stage} and {next_stage}.",
                    "severity": severity,
                })
                anomaly_penalty += 25.0 if dropoff_rate >= 0.85 else 15.0

                recommendations.append({
                    "target": f"{curr_stage} -> {next_stage}",
                    "action": f"Optimize landing messaging and trust signals to reduce severe {dropoff_rate:.1%} drop-off between {curr_stage} and {next_stage}.",
                    "priority": "HIGH" if severity == SIGNAL_CRITICAL else "MEDIUM",
                })

    # 2. Cluster Conversion Rate Outliers (Z-Score)
    cluster_breakdown = results_json.get("cluster_breakdown") or {}
    if not isinstance(cluster_breakdown, dict):
        cluster_breakdown = {}

    rates: list[tuple[str, float]] = []
    for cid, data in cluster_breakdown.items():
        if isinstance(data, dict):
            conv = _safe_float(data.get("conversion_rate"))
            rates.append((str(cid), conv))

    if len(rates) >= 3:
        vals = [r[1] for r in rates]
        mean_val = sum(vals) / len(vals)
        variance = sum((x - mean_val) ** 2 for x in vals) / len(vals)
        std_dev = math.sqrt(variance)

        if std_dev > 0.0001:
            for cid, rate in rates:
                z_score = (rate - mean_val) / std_dev
                if abs(z_score) >= outlier_z_threshold:
                    severity = SIGNAL_WATCH if z_score > 0 else SIGNAL_CRITICAL
                    outlier_item = {
                        "cluster_id": cid,
                        "conversion_rate": round(rate, 4),
                        "z_score": round(z_score, 2),
                        "deviation_direction": "HIGH" if z_score > 0 else "LOW",
                        "severity": severity,
                    }
                    cluster_outliers.append(outlier_item)
                    anomalies.append({
                        "type": "CLUSTER_CONVERSION_OUTLIER",
                        "description": f"Cluster '{cid}' conversion ({rate:.1%}) deviates by {z_score:+.2f} std dev from mean.",
                        "severity": severity,
                    })
                    anomaly_penalty += 15.0 if z_score < 0 else 5.0

                    if z_score < 0:
                        recommendations.append({
                            "target": f"Cluster '{cid}'",
                            "action": f"Investigate specific friction or pricing mismatch for low-performing cluster '{cid}' ({rate:.1%} vs average {mean_val:.1%}).",
                            "priority": "HIGH",
                        })
                    else:
                        recommendations.append({
                            "target": f"Cluster '{cid}'",
                            "action": f"Analyze high conversion drivers in top-performing cluster '{cid}' ({rate:.1%} vs average {mean_val:.1%}) to scale segment acquisition.",
                            "priority": "MEDIUM",
                        })

    # 3. Overall Anomaly Score & Status
    anomaly_score = min(ANOMALY_SCORE_CAP, round(anomaly_penalty, 2))

    if anomaly_score >= 40.0:
        status = "CRITICAL"
        overall_severity = SIGNAL_CRITICAL
    elif anomaly_score >= 15.0:
        status = "WATCH"
        overall_severity = SIGNAL_WATCH
    else:
        status = "NORMAL"
        overall_severity = SIGNAL_OK

    # 4. Human-Readable & Markdown Diagnostic Narrative
    sentences: list[str] = []
    if not anomalies:
        sentences.append("No statistical anomalies or abnormal drop-off spikes detected in simulation results.")
    else:
        sentences.append(
            f"Detected {len(anomalies)} anomaly signal(s) with an anomaly score of {anomaly_score}/100 ({status})."
        )
        if stage_spikes:
            top_spike = stage_spikes[0]
            sentences.append(
                f"Primary bottleneck: {top_spike['dropoff_rate']:.1%} drop-off from {top_spike['stage_from']} to {top_spike['stage_to']}."
            )
        if cluster_outliers:
            sentences.append(f"Identified {len(cluster_outliers)} cluster conversion outlier(s).")

    narrative = " ".join(sentences)

    key_signals: list[dict[str, Any]] = [
        {
            "label": "anomaly_status",
            "value": status,
            "severity": overall_severity,
            "display": f"Anomaly Status: {status}",
        },
        {
            "label": "anomaly_score",
            "value": anomaly_score,
            "severity": overall_severity,
            "display": f"Anomaly Score: {anomaly_score}/100",
        },
        {
            "label": "stage_spikes_count",
            "value": len(stage_spikes),
            "severity": SIGNAL_CRITICAL if stage_spikes else SIGNAL_OK,
            "display": f"{len(stage_spikes)} Stage Drop-off Spike(s)",
        },
        {
            "label": "recommendations_count",
            "value": len(recommendations),
            "severity": SIGNAL_WATCH if recommendations else SIGNAL_OK,
            "display": f"{len(recommendations)} Recommendation(s)",
        },
    ]

    return {
        "anomaly_score": anomaly_score,
        "status": status,
        "anomalies_count": len(anomalies),
        "anomalies": anomalies,
        "stage_spikes": stage_spikes,
        "cluster_outliers": cluster_outliers,
        "recommendations": recommendations,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "detect_simulation_anomalies",
    "ANOMALY_SCORE_CAP",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "DEFAULT_STAGES",
]

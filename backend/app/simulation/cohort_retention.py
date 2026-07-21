"""
Pure cohort retention projection for completed simulation results.

Takes a simulation's ``results_json`` (cluster_breakdown + domain_findings)
and projects retention curves, churn rates, and LTV estimates per cluster.

Uses the cluster conversion rate as a retention proxy, adjusted by
RetentionArchitect findings when available. Projects survival curves at
standard intervals (day 1, 7, 30, 90, 180, 365) using a decay model
calibrated to Indian SaaS/D2C benchmarks.

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.schemas.cohort_retention import (
    ClusterRetentionProfile,
    CohortRetentionOut,
    RetentionCurvePoint,
    SegmentRetentionSummary,
)

# Standard retention measurement intervals.
RETENTION_DAYS: list[int] = [1, 7, 30, 90, 180, 365]

# Benchmark survival rates at each interval for a "healthy" SaaS/D2C product
# (fraction of converted users still active). These are the ceiling values
# that a cluster with 100% conversion would achieve.
BENCHMARK_SURVIVAL: dict[int, float] = {
    1: 0.82,
    7: 0.55,
    30: 0.32,
    90: 0.18,
    180: 0.12,
    365: 0.08,
}

# Churn risk thresholds based on day-30 survival rate.
CHURN_RISK_THRESHOLDS: dict[str, float] = {
    "CRITICAL": 0.08,   # day30 < 8%
    "HIGH": 0.15,       # day30 < 15%
    "MEDIUM": 0.25,     # day30 < 25%
    "LOW": 0.25,        # day30 >= 25%
}

# Churn trigger labels mapped from RetentionArchitect metric keys.
CHURN_TRIGGER_MAP: dict[str, str] = {
    "price": "Pricing / Will-pay barrier",
    "onboarding": "Onboarding drop-off",
    "feature": "Feature depth / engagement",
    "trust": "Trust / brand deficit",
    "competition": "Competitive displacement",
    "support": "Support / bug friction",
    "habit": "Habit loop not formed",
}


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


def _extract_retention_findings(
    domain_findings: list[Any],
) -> dict[str, dict[str, Any]]:
    """
    Extract per-cluster retention metrics from domain_findings.

    Returns a dict of cluster_id → {metric_key: value, ...}.
    """
    retention_data: dict[str, dict[str, Any]] = {}

    for finding in domain_findings or []:
        if not isinstance(finding, dict):
            continue
        arch = str(finding.get("architect_name", "")).lower()
        if "retention" not in arch:
            continue

        cid = str(finding.get("cluster_id", ""))
        if not cid:
            continue

        metric = str(finding.get("metric_affected", ""))
        actual = _safe_float(finding.get("actual_value", 0.0))
        benchmark = _safe_float(finding.get("healthy_benchmark", 0.0))

        if cid not in retention_data:
            retention_data[cid] = {}

        retention_data[cid][metric] = {
            "actual": actual,
            "benchmark": benchmark,
            "delta": _safe_float(finding.get("delta", 0.0)),
            "severity": str(finding.get("severity", "INFO")),
        }

    return retention_data


def _infer_churn_trigger(
    retention_data: dict[str, Any],
    conversion_rate: float,
) -> str:
    """
    Infer the primary churn trigger for a cluster from available metrics.
    Falls back to conversion-rate-based heuristics when retention data is sparse.
    """
    if not retention_data:
        if conversion_rate < 0.01:
            return CHURN_TRIGGER_MAP["price"]
        if conversion_rate < 0.03:
            return CHURN_TRIGGER_MAP["onboarding"]
        return CHURN_TRIGGER_MAP["habit"]

    # Score each churn domain from available metrics
    scores: dict[str, float] = {}

    # Pricing: will_pay_probability
    will_pay = _safe_float(retention_data.get("will_pay_probability", {}).get("actual", 0.5))
    scores["price"] = 1.0 - will_pay

    # Onboarding: onboarding_completion_rate
    onboard = _safe_float(retention_data.get("onboarding_completion_rate", {}).get("actual", 0.7))
    scores["onboarding"] = 1.0 - onboard

    # Feature: feature_depth_score
    feature = _safe_float(retention_data.get("feature_depth_score", {}).get("actual", 0.4))
    scores["feature"] = 1.0 - feature

    # Trust: brand_deficit_multiplier
    brand = _safe_float(retention_data.get("brand_deficit_multiplier", {}).get("actual", 0.75))
    scores["trust"] = max(0.0, 1.0 - brand)

    # Habit: habit_loop_formation_days
    habit_days = _safe_float(retention_data.get("habit_loop_formation_days", {}).get("actual", 21.0))
    scores["habit"] = min(1.0, habit_days / 60.0)

    if scores:
        return CHURN_TRIGGER_MAP[max(scores, key=scores.get)]

    return CHURN_TRIGGER_MAP["habit"]


def _compute_survival_curve(
    conversion_rate: float,
    retention_data: dict[str, Any],
    benchmark_cr: float = 0.05,
) -> list[float]:
    """
    Compute survival rates at each RETENTION_DAYS interval.

    Uses the cluster's conversion rate relative to the benchmark to scale
    the benchmark survival curve. Clusters above benchmark get a boost;
    clusters below get a penalty. RetentionArchitect metrics (when available)
    further adjust day-30 and day-90 survival.
    """
    # Conversion-to-retention scaling factor
    if conversion_rate > 0:
        cr_ratio = conversion_rate / benchmark_cr
        # Clamp to [0.2, 2.5] to avoid extreme projections
        cr_ratio = max(0.2, min(2.5, cr_ratio))
    else:
        cr_ratio = 0.2

    survival: list[float] = []
    for day in RETENTION_DAYS:
        benchmark = BENCHMARK_SURVIVAL.get(day, 0.05)

        # Scale by conversion ratio with diminishing returns
        scaled = benchmark * (0.5 + 0.5 * cr_ratio)
        scaled = min(0.95, scaled)

        # Adjust day-30 and day-90 from RetentionArchitect data if available
        if day == 30:
            d30_actual = _safe_float(
                retention_data.get("day30_survival", {}).get("actual", -1)
            )
            if d30_actual >= 0:
                scaled = d30_actual
        elif day == 90:
            d90_actual = _safe_float(
                retention_data.get("day90_survival", {}).get("actual", -1)
            )
            if d90_actual >= 0:
                scaled = d90_actual
        elif day == 7:
            d7_actual = _safe_float(
                retention_data.get("day7_survival", {}).get("actual", -1)
            )
            if d7_actual >= 0:
                scaled = d7_actual
        elif day == 1:
            d1_actual = _safe_float(
                retention_data.get("day1_survival", {}).get("actual", -1)
            )
            if d1_actual >= 0:
                scaled = d1_actual

        # Ensure monotonic non-increasing survival curve
        if survival and scaled > survival[-1]:
            scaled = survival[-1]

        survival.append(round(max(0.0, min(1.0, scaled)), 4))

    return survival


def _compute_ltv_score(
    d90: float,
    annual_pref: float,
    reeng_30: float,
    price_ceiling: float,
    aov: float,
) -> float:
    """Compute a 0-1 LTV score for a cluster."""
    ceiling_ratio = min(1.0, price_ceiling / max(aov * 3, 1))
    return round(
        d90 * 0.40
        + annual_pref * 0.25
        + reeng_30 * 0.15
        + ceiling_ratio * 0.20,
        4,
    )


def _churn_risk_label(d30: float) -> str:
    """Map day-30 survival to a churn risk label."""
    if d30 < CHURN_RISK_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if d30 < CHURN_RISK_THRESHOLDS["HIGH"]:
        return "HIGH"
    if d30 < CHURN_RISK_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _churn_risk_score(d30: float) -> float:
    """Map day-30 survival to a 0-1 risk score (1 = highest risk)."""
    return round(max(0.0, min(1.0, 1.0 - d30 / 0.32)), 4)


def _build_segment_summary(
    profiles: list[ClusterRetentionProfile],
) -> list[SegmentRetentionSummary]:
    """Aggregate cluster profiles into churn-risk segment summaries."""
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "weight": 0.0, "d30_sum": 0.0, "d90_sum": 0.0, "ltv_sum": 0.0, "risk_sum": 0.0}
    )

    for p in profiles:
        b = buckets[p.churn_risk]
        b["count"] += 1
        b["weight"] += p.population_weight
        b["d30_sum"] += p.day30_survival
        b["d90_sum"] += p.day90_survival
        b["ltv_sum"] += p.ltv_score
        b["risk_sum"] += _churn_risk_score(p.day30_survival)

    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    out: list[SegmentRetentionSummary] = []
    for seg in order:
        if seg not in buckets:
            continue
        b = buckets[seg]
        n = max(1, int(b["count"]))
        out.append(
            SegmentRetentionSummary(
                segment=seg,
                cluster_count=int(b["count"]),
                total_population_weight=round(b["weight"], 6),
                mean_day30_survival=round(b["d30_sum"] / n, 4),
                mean_day90_survival=round(b["d90_sum"] / n, 4),
                mean_ltv_score=round(b["ltv_sum"] / n, 4),
                mean_churn_risk_score=round(b["risk_sum"] / n, 4),
            )
        )
    return out


def _build_recommendations(
    profiles: list[ClusterRetentionProfile],
    overall_d30: float,
    overall_d90: float,
    highest_churn_stage: str,
    reeng_viable: bool,
) -> list[str]:
    """Generate actionable retention recommendations."""
    tips: list[str] = []

    critical = [p for p in profiles if p.churn_risk == "CRITICAL"]
    high = [p for p in profiles if p.churn_risk == "HIGH"]
    best = max(profiles, key=lambda p: p.day30_survival) if profiles else None

    if critical:
        top = critical[0]
        tips.append(
            f"Urgent: '{top.cluster_id}' has CRITICAL churn risk "
            f"(day-30 survival {top.day30_survival:.1%}). "
            f"Primary trigger: {top.churn_trigger}. "
            "Address immediately with targeted re-engagement."
        )

    if high:
        top = high[0]
        tips.append(
            f"High churn risk on '{top.cluster_id}' "
            f"(day-30 survival {top.day30_survival:.1%}). "
            f"Focus: {top.churn_trigger}."
        )

    if highest_churn_stage:
        tips.append(
            f"Highest churn stage is {highest_churn_stage} — "
            "implement stage-specific retention interventions."
        )

    if reeng_viable:
        tips.append(
            "Re-engagement is viable for some clusters (30-day re-engagement "
            "probability > 15%). Launch targeted win-back campaigns."
        )

    if best and best.churn_risk in ("LOW", "MEDIUM"):
        tips.append(
            f"Learn from '{best.cluster_id}' (day-30 survival "
            f"{best.day30_survival:.1%}) — replicate its success factors "
            "across weaker segments."
        )

    if overall_d30 < 0.15:
        tips.append(
            f"Market-wide day-30 survival is {overall_d30:.1%} — below the "
            "0.15 threshold. Prioritise core product retention over acquisition."
        )

    if not tips:
        tips.append(
            "Retention looks healthy — maintain current engagement strategies "
            "and monitor for regressions."
        )

    return tips[:6]


def build_cohort_retention(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    cluster_summaries: list[dict[str, Any]] | None = None,
    cluster_registry: dict[str, dict[str, Any]] | None = None,
    aov: float = 999.0,
    benchmark_cr: float = 0.05,
    limit: int = 52,
) -> CohortRetentionOut:
    """
    Build a cohort retention projection from persisted simulation results.

    Safe on empty / malformed payloads — returns a zero-state projection
    rather than raising so the API can always respond 200 for completed sims.
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
    total_converted = _safe_int(data.get("converted"))
    if total_converted <= 0 and total_agents > 0:
        total_converted = int(round(overall * total_agents))

    # Extract retention findings from domain_findings
    domain_findings = data.get("domain_findings") or []
    retention_data = _extract_retention_findings(domain_findings)

    # Build cluster summaries lookup
    summary_by_id: dict[str, dict[str, Any]] = {}
    if cluster_summaries:
        for row in cluster_summaries:
            if isinstance(row, dict) and row.get("cluster_id"):
                summary_by_id[str(row["cluster_id"])] = row

    total_assigned = sum(
        max(0, _safe_int(s.get("agents_assigned"))) for s in summary_by_id.values()
    )

    registry = cluster_registry or {}
    breakdown = data.get("cluster_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}

    cluster_ids = {str(k) for k in breakdown.keys()} | set(summary_by_id.keys())
    limit = max(1, min(int(limit) if isinstance(limit, int) else 52, 52))

    profiles: list[ClusterRetentionProfile] = []

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

        # Population weight
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

        # Agents converted
        agents_converted = _safe_int(summary.get("agents_converted"))
        if agents_converted is None and agents_assigned:
            agents_converted = int(round(cr * agents_assigned))
        elif agents_converted is None:
            agents_converted = int(round(cr * total_converted / max(overall, 0.001))) if overall > 0 else 0

        # Retention metrics
        cl_retention = retention_data.get(cid, {})
        survival_rates = _compute_survival_curve(cr, cl_retention, benchmark_cr)

        # Build curve points
        curve: list[RetentionCurvePoint] = []
        prev_survival = 1.0
        for i, day in enumerate(RETENTION_DAYS):
            s = survival_rates[i]
            churn = round(1.0 - s, 4)
            active = int(round(s * agents_converted)) if agents_converted > 0 else 0
            curve.append(
                RetentionCurvePoint(
                    day=day,
                    survival_rate=s,
                    cumulative_churn=churn,
                    active_users=active,
                )
            )
            prev_survival = s

        d30 = survival_rates[2] if len(survival_rates) > 2 else 0.0
        d90 = survival_rates[3] if len(survival_rates) > 3 else 0.0
        d365 = survival_rates[5] if len(survival_rates) > 5 else 0.0

        # Churn trigger
        churn_trigger = _infer_churn_trigger(cl_retention, cr)

        # LTV
        annual_pref = _safe_float(
            cl_retention.get("annual_payment_probability", {}).get("actual", 0.2)
        )
        reeng_30 = _safe_float(
            cl_retention.get("reengagement_probability_30d", {}).get("actual", 0.10)
        )
        price_ceiling = _safe_float(
            cl_retention.get("price_ceiling", {}).get("actual", aov)
        )
        ltv_score = _compute_ltv_score(d90, annual_pref, reeng_30, price_ceiling, aov)
        ltv_estimate = round(ltv_score * d365 * aov * 12, 2)  # annualized

        churn_risk = _churn_risk_label(d30)
        reeng_viable = reeng_30 > 0.15

        name = _cluster_name(raw, str(registry.get(cid, {}).get("name", cid)))

        profiles.append(
            ClusterRetentionProfile(
                cluster_id=cid,
                cluster_name=name,
                population_weight=round(weight, 6),
                conversion_rate=round(cr, 4),
                agents_converted=agents_converted,
                retention_curve=curve,
                day30_survival=d30,
                day90_survival=d90,
                churn_risk=churn_risk,
                churn_trigger=churn_trigger,
                ltv_score=ltv_score,
                ltv_estimate=ltv_estimate,
                reengagement_viable=reeng_viable,
                reengagement_prob_30d=reeng_30,
            )
        )

    # Sort by population weight desc, then conversion rate desc
    profiles.sort(key=lambda p: (-p.population_weight, -p.conversion_rate, p.cluster_id))
    profiles = profiles[:limit]

    # Market-level aggregates
    total_weight = sum(p.population_weight for p in profiles) or 1.0
    market_d30 = round(
        sum(p.day30_survival * p.population_weight for p in profiles) / total_weight,
        4,
    )
    market_d90 = round(
        sum(p.day90_survival * p.population_weight for p in profiles) / total_weight,
        4,
    )
    market_d365 = round(
        sum(p.retention_curve[-1].survival_rate * p.population_weight for p in profiles) / total_weight,
        4,
    )

    # Highest churn stage
    drops: dict[str, float] = {}
    for p in profiles:
        for i in range(1, len(p.retention_curve)):
            prev = p.retention_curve[i - 1].survival_rate
            curr = p.retention_curve[i].survival_rate
            stage = f"day{p.retention_curve[i].day}"
            drops[stage] = drops.get(stage, 0.0) + (prev - curr) * p.population_weight
    highest_churn_stage = max(drops, key=drops.get) if drops else "day30"

    # Best / worst retention clusters
    best_cluster = (
        max(profiles, key=lambda p: p.day30_survival).cluster_id if profiles else ""
    )
    worst_cluster = (
        min(profiles, key=lambda p: p.day30_survival).cluster_id if profiles else ""
    )

    # Re-engagement viability
    reeng_viable = any(p.reengagement_viable for p in profiles)

    # Churn trigger distribution
    trigger_dist: dict[str, int] = defaultdict(int)
    for p in profiles:
        trigger_dist[p.churn_trigger] += 1

    # Segment summary
    segment_summary = _build_segment_summary(profiles)

    # Recommendations
    recommendations = _build_recommendations(
        profiles, market_d30, market_d90, highest_churn_stage, reeng_viable
    )

    return CohortRetentionOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        overall_conversion=round(overall, 4),
        total_agents=total_agents,
        total_converted=total_converted,
        market_day30_survival=market_d30,
        market_day90_survival=market_d90,
        market_day365_survival=market_d365,
        highest_churn_stage=highest_churn_stage,
        best_retention_cluster=best_cluster,
        worst_retention_cluster=worst_cluster,
        reengagement_viable=reeng_viable,
        churn_trigger_distribution=dict(trigger_dist),
        cluster_profiles=profiles,
        segment_summary=segment_summary,
        recommendations=recommendations,
        product_type_detected=str(data.get("product_type_detected") or ""),
        primary_failure_domain=str(data.get("primary_failure_domain") or "unknown"),
        signal_quality=signal_quality,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "retention_days": RETENTION_DAYS,
            "benchmark_cr": benchmark_cr,
            "cluster_count": len(profiles),
            "retention_findings_used": len(retention_data),
            "cluster_summaries_used": bool(cluster_summaries),
        },
    )


__all__ = [
    "RETENTION_DAYS",
    "BENCHMARK_SURVIVAL",
    "CHURN_TRIGGER_MAP",
    "build_cohort_retention",
]

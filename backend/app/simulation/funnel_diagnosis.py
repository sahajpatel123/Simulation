"""
Pure funnel-bottleneck diagnosis for completed simulation results.

Takes ``results_json`` (and optional ``cluster_run_summaries`` rows) and
produces a structured diagnosis:

  * Per-stage drop-off vs Markov healthy benchmarks
  * Primary bottleneck stage (highest absolute agent loss among forward stages)
  * Cluster drag ranking (population-weighted contribution to lost conversion)
  * Aggregated drop-trigger histogram from cluster_run_summaries
  * Ranked recommendations with estimated conversion lift
  * Health score (0–100) and recoverable-conversion estimate

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.schemas.funnel_diagnosis import (
    ClusterDrag,
    DiagnosisRecommendation,
    DropTriggerCount,
    FunnelDiagnosisOut,
    StageDiagnosis,
)

# Forward funnel stages used for bottleneck ranking. Terminal / re-entry
# states (ABANDON, RETURN, PURCHASE) are reported but never nominated as
# the primary bottleneck — PURCHASE has no "drop" in the conversion sense.
FORWARD_STAGES: tuple[str, ...] = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE")

# Healthy drop-off rates derived from the base Markov transition matrix
# (see app.simulation.markov). ARRIVE→ABANDON ≈ 0.13, BROWSE→ABANDON ≈ 0.38,
# CONSIDER→ABANDON ≈ 0.38, DECIDE→ABANDON ≈ 0.55. PURCHASE is terminal.
HEALTHY_DROP_OFF: dict[str, float] = {
    "ARRIVE": 0.13,
    "BROWSE": 0.38,
    "CONSIDER": 0.38,
    "DECIDE": 0.55,
    "PURCHASE": 0.0,
    "ABANDON": 0.0,
    "RETURN": 0.20,
}

# Stage → (primary domain label, recommended architect names)
STAGE_DOMAIN_MAP: dict[str, tuple[str, list[str]]] = {
    "ARRIVE": (
        "ACQUISITION",
        ["MarketTimingArchitect", "DemographicInteractionArchitect"],
    ),
    "BROWSE": (
        "ONBOARDING",
        ["OnboardingArchitect", "TrustArchitect", "ViralityArchitect"],
    ),
    "CONSIDER": (
        "TRUST",
        ["TrustArchitect", "CompetitiveDynamicsArchitect", "FeatureAdoptionArchitect"],
    ),
    "DECIDE": (
        "PRICING",
        ["PricingArchitect", "TrustArchitect", "PurchaseDecisionArchitect"],
    ),
    "PURCHASE": (
        "RETENTION",
        ["RetentionArchitect", "SupportFrictionArchitect", "AftersalesLifecycleArchitect"],
    ),
    "ABANDON": (
        "RETENTION",
        ["RetentionArchitect", "ViralityArchitect"],
    ),
    "RETURN": (
        "RETENTION",
        ["RetentionArchitect", "ViralityArchitect"],
    ),
}

# Partial recovery model: fraction of excess drop-off that is realistically
# recoverable if the bottleneck domain is fixed. Conservative so founders
# do not over-index on an optimistic lift estimate.
RECOVERY_FRACTION: float = 0.35

_SEVERITY_ORDER: dict[str, int] = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


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


def _severity_for_delta(delta: float) -> str:
    """Map excess drop-off (actual − healthy) to severity."""
    if delta >= 0.20:
        return "CRITICAL"
    if delta >= 0.08:
        return "WARNING"
    return "INFO"


def _extract_stage_rows(results: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Normalise stage metrics from either ``stage_metrics`` (FunnelResult) or
    ``stage_aggregations`` (ResultsAggregator) payloads.
    """
    raw = results.get("stage_metrics") or results.get("stage_aggregations") or []
    if not isinstance(raw, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("state") or item.get("stage") or "").upper().strip()
        if not stage:
            continue
        drop = _safe_float(
            item.get("drop_off_rate", item.get("mean_drop_off_rate"))
        )
        entry = _safe_float(item.get("entry_rate", item.get("mean_entry_rate")))
        count = _safe_int(item.get("agent_count", item.get("agents")))
        rows.append(
            {
                "stage": stage,
                "drop_off_rate": max(0.0, min(1.0, drop)),
                "entry_rate": max(0.0, min(1.0, entry)),
                "agent_count": max(0, count),
            }
        )
    return rows


def _infer_stages_from_counts(
    stage_counts: dict[str, Any],
    total_agents: int,
) -> list[dict[str, Any]]:
    """Build stage rows from a ``stage_counts`` map when metrics are missing."""
    if total_agents <= 0 or not isinstance(stage_counts, dict):
        return []

    ordered = ["ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE", "ABANDON", "RETURN"]
    rows: list[dict[str, Any]] = []
    prev = total_agents
    for stage in ordered:
        count = _safe_int(stage_counts.get(stage))
        entry = count / total_agents if total_agents else 0.0
        raw_drop = 1.0 - (count / prev) if prev > 0 else 0.0
        drop = max(0.0, min(1.0, raw_drop))
        rows.append(
            {
                "stage": stage,
                "drop_off_rate": round(drop, 4),
                "entry_rate": round(entry, 4),
                "agent_count": count,
            }
        )
        prev = max(1, count)
    return rows


def _cluster_conversion(raw: Any) -> float:
    if isinstance(raw, dict):
        return _safe_float(raw.get("conversion_rate", raw.get("conversion")))
    return _safe_float(raw)


def _build_stage_diagnoses(
    stage_rows: list[dict[str, Any]],
) -> tuple[list[StageDiagnosis], str | None]:
    diagnoses: list[StageDiagnosis] = []
    best_stage: str | None = None
    best_loss = -1
    best_delta = -1.0

    for row in stage_rows:
        stage = row["stage"]
        drop = float(row["drop_off_rate"])
        count = int(row["agent_count"])
        # Agents lost at this stage ≈ drop_off × agents who entered the prior
        # count. When only the current count is known, approximate as
        # drop / (1 − drop) × count for non-terminal stages.
        if drop < 1.0 and count >= 0:
            prior = int(round(count / (1.0 - drop))) if drop < 0.999 else count
            agents_lost = max(0, prior - count)
        else:
            agents_lost = count if stage == "ABANDON" else 0

        healthy = HEALTHY_DROP_OFF.get(stage, 0.35)
        delta = round(drop - healthy, 4)
        severity = _severity_for_delta(delta) if stage in FORWARD_STAGES else "INFO"
        domain, architects = STAGE_DOMAIN_MAP.get(stage, ("UNKNOWN", []))

        diagnoses.append(
            StageDiagnosis(
                stage=stage,
                agent_count=count,
                entry_rate=round(float(row["entry_rate"]), 4),
                drop_off_rate=round(drop, 4),
                agents_lost=agents_lost,
                healthy_drop_off=healthy,
                delta_from_healthy=delta,
                severity=severity,
                primary_domain=domain,
                recommended_architects=list(architects),
                is_primary_bottleneck=False,
            )
        )

        if stage in FORWARD_STAGES and (
            agents_lost > best_loss
            or (agents_lost == best_loss and delta > best_delta)
        ):
            best_loss = agents_lost
            best_delta = delta
            best_stage = stage

    if best_stage is None and diagnoses:
        # Fall back to the forward stage with the largest positive delta.
        candidates = [
            d for d in diagnoses if d.stage in FORWARD_STAGES and d.delta_from_healthy > 0
        ]
        if candidates:
            best_stage = max(candidates, key=lambda d: d.delta_from_healthy).stage

    for d in diagnoses:
        if d.stage == best_stage:
            d.is_primary_bottleneck = True

    return diagnoses, best_stage


def _build_cluster_drag(
    results: dict[str, Any],
    summaries: list[dict[str, Any]] | None,
    limit: int = 10,
) -> list[ClusterDrag]:
    breakdown = results.get("cluster_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}

    summary_by_id: dict[str, dict[str, Any]] = {}
    if summaries:
        for row in summaries:
            if isinstance(row, dict) and row.get("cluster_id"):
                summary_by_id[str(row["cluster_id"])] = row

    # Population weights: prefer summary agents_assigned share, else equal.
    total_agents_assigned = sum(
        max(0, _safe_int(s.get("agents_assigned"))) for s in summary_by_id.values()
    )

    drag: list[ClusterDrag] = []
    for cid, raw_cr in breakdown.items():
        cid_s = str(cid)
        cr = max(0.0, min(1.0, _cluster_conversion(raw_cr)))
        summary = summary_by_id.get(cid_s, {})
        agents_assigned = _safe_int(summary.get("agents_assigned"))
        if total_agents_assigned > 0 and agents_assigned > 0:
            weight = agents_assigned / total_agents_assigned
        else:
            # Fall back to uniform weight across observed clusters so rankings
            # remain meaningful when summaries are absent.
            weight = 1.0 / max(1, len(breakdown))

        lost_share = round((1.0 - cr) * weight, 6)
        name = ""
        if isinstance(raw_cr, dict):
            name = str(raw_cr.get("cluster_name") or raw_cr.get("name") or "")
        drag.append(
            ClusterDrag(
                cluster_id=cid_s,
                cluster_name=name or cid_s,
                conversion_rate=round(cr, 4),
                population_weight=round(weight, 6),
                lost_conversion_share=lost_share,
                primary_drop_trigger=(
                    str(summary["primary_drop_trigger"])
                    if summary.get("primary_drop_trigger")
                    else None
                ),
                mean_drop_state=(
                    str(summary["mean_drop_state"])
                    if summary.get("mean_drop_state")
                    else None
                ),
            )
        )

    drag.sort(key=lambda c: (-c.lost_conversion_share, c.cluster_id))
    return drag[: max(1, limit)] if drag else []


def _build_drop_triggers(
    summaries: list[dict[str, Any]] | None,
) -> list[DropTriggerCount]:
    if not summaries:
        return []

    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"clusters": 0.0, "agents": 0.0, "conv_sum": 0.0}
    )
    for row in summaries:
        if not isinstance(row, dict):
            continue
        trigger = str(row.get("primary_drop_trigger") or "unknown").strip() or "unknown"
        agents = max(0, _safe_int(row.get("agents_assigned")))
        cr = max(0.0, min(1.0, _safe_float(row.get("conversion_rate"))))
        buckets[trigger]["clusters"] += 1
        buckets[trigger]["agents"] += agents
        buckets[trigger]["conv_sum"] += cr

    out: list[DropTriggerCount] = []
    for trigger, stats in buckets.items():
        n = max(1, int(stats["clusters"]))
        out.append(
            DropTriggerCount(
                trigger=trigger,
                cluster_count=int(stats["clusters"]),
                agents_affected=int(stats["agents"]),
                mean_conversion=round(stats["conv_sum"] / n, 4),
            )
        )
    out.sort(key=lambda t: (-t.agents_affected, -t.cluster_count, t.trigger))
    return out


def _estimate_recoverable(
    overall_conversion: float,
    primary: StageDiagnosis | None,
) -> float | None:
    if primary is None:
        return None
    excess = max(0.0, primary.delta_from_healthy)
    if excess <= 0:
        return round(overall_conversion, 4)
    # Lift ≈ excess_drop × entry_rate × recovery_fraction, capped so the
    # estimate never exceeds a soft 3× of current conversion or 0.5 absolute.
    lift = excess * max(0.0, primary.entry_rate) * RECOVERY_FRACTION
    lift = min(lift, max(0.05, overall_conversion * 2.0), 0.25)
    return round(min(0.99, overall_conversion + lift), 4)


def _build_recommendations(
    stages: list[StageDiagnosis],
    primary_stage: str | None,
    cluster_drag: list[ClusterDrag],
    overall_conversion: float,
    primary_failure_domain: str,
) -> list[DiagnosisRecommendation]:
    recs: list[DiagnosisRecommendation] = []
    related = [c.cluster_id for c in cluster_drag[:3]]

    # Always surface the primary bottleneck first when it exists.
    primary = next((s for s in stages if s.stage == primary_stage), None)
    if primary is not None and primary.delta_from_healthy > 0:
        lift = (_estimate_recoverable(overall_conversion, primary) or overall_conversion)
        estimated = round(max(0.0, lift - overall_conversion), 4)
        recs.append(
            DiagnosisRecommendation(
                priority=1,
                stage=primary.stage,
                domain=primary.primary_domain,
                severity=primary.severity,
                title=f"Fix {primary.stage} bottleneck ({primary.primary_domain})",
                rationale=(
                    f"{primary.stage} drop-off is {primary.drop_off_rate:.0%} "
                    f"(healthy ≤ {primary.healthy_drop_off:.0%}; "
                    f"Δ={primary.delta_from_healthy:+.0%}). "
                    f"Approximately {primary.agents_lost} simulated agents leave here."
                ),
                estimated_lift=estimated,
                architects=list(primary.recommended_architects),
                related_clusters=related,
            )
        )

    # Secondary: other forward stages with WARNING+ severity.
    priority = 2
    for stage in stages:
        if stage.stage == primary_stage:
            continue
        if stage.stage not in FORWARD_STAGES:
            continue
        if stage.severity not in {"CRITICAL", "WARNING"}:
            continue
        if stage.delta_from_healthy <= 0:
            continue
        lift = min(0.12, max(0.01, stage.delta_from_healthy * stage.entry_rate * 0.25))
        recs.append(
            DiagnosisRecommendation(
                priority=priority,
                stage=stage.stage,
                domain=stage.primary_domain,
                severity=stage.severity,
                title=f"Reduce {stage.stage} drop-off",
                rationale=(
                    f"{stage.stage} is {stage.delta_from_healthy:+.0%} above the "
                    f"healthy benchmark. Domain focus: {stage.primary_domain}."
                ),
                estimated_lift=round(lift, 4),
                architects=list(stage.recommended_architects),
                related_clusters=related[:2],
            )
        )
        priority += 1
        if priority > 5:
            break

    # Cluster-level: surface the worst drag cluster when conversion is low.
    if cluster_drag and overall_conversion < 0.05:
        worst = cluster_drag[0]
        trigger = worst.primary_drop_trigger or worst.mean_drop_state or "unknown"
        recs.append(
            DiagnosisRecommendation(
                priority=priority,
                stage=worst.mean_drop_state or (primary_stage or "DECIDE"),
                domain=primary_failure_domain or "MARKET",
                severity="WARNING" if overall_conversion < 0.03 else "INFO",
                title=f"Re-target or redesign for {worst.cluster_id}",
                rationale=(
                    f"Cluster '{worst.cluster_name}' contributes "
                    f"{worst.lost_conversion_share:.1%} of lost conversion share "
                    f"(CR={worst.conversion_rate:.1%}). Primary trigger: {trigger}."
                ),
                estimated_lift=round(min(0.08, worst.lost_conversion_share * 0.4), 4),
                architects=[],
                related_clusters=[worst.cluster_id],
            )
        )

    recs.sort(key=lambda r: (r.priority, _SEVERITY_ORDER.get(r.severity, 9)))
    return recs


def _health_score(
    overall_conversion: float,
    stages: list[StageDiagnosis],
    primary: StageDiagnosis | None,
) -> int:
    # Base from conversion vs Indian SaaS/D2C 3–5% benchmark band.
    if overall_conversion >= 0.08:
        base = 85
    elif overall_conversion >= 0.05:
        base = 72
    elif overall_conversion >= 0.03:
        base = 58
    elif overall_conversion >= 0.01:
        base = 40
    else:
        base = 22

    penalty = 0
    for s in stages:
        if s.stage not in FORWARD_STAGES:
            continue
        if s.severity == "CRITICAL":
            penalty += 12
        elif s.severity == "WARNING":
            penalty += 6
    if primary is not None and primary.severity == "CRITICAL":
        penalty += 5

    return int(max(5, min(99, base - penalty)))


def build_funnel_diagnosis(
    results: Any,
    *,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    cluster_summaries: list[dict[str, Any]] | None = None,
    cluster_limit: int = 10,
) -> FunnelDiagnosisOut:
    """
    Build a complete funnel bottleneck diagnosis from persisted results.

    Safe on empty / malformed payloads — returns a zero-state diagnosis
    rather than raising so the API can always respond 200 for completed sims.
    """
    data = _coerce_results(results)
    overall = _safe_float(
        data.get("population_weighted_conversion", data.get("conversion_rate"))
    )
    overall = max(0.0, min(1.0, overall))
    total_agents = _safe_int(data.get("total_agents"))
    converted = _safe_int(data.get("converted"))
    if converted <= 0 and total_agents > 0:
        converted = int(round(overall * total_agents))

    stage_rows = _extract_stage_rows(data)
    if not stage_rows and isinstance(data.get("stage_counts"), dict):
        stage_rows = _infer_stages_from_counts(data["stage_counts"], total_agents)

    stages, primary_stage = _build_stage_diagnoses(stage_rows)
    primary_obj = next((s for s in stages if s.stage == primary_stage), None)
    bottleneck_severity = primary_obj.severity if primary_obj else "INFO"

    cluster_drag = _build_cluster_drag(data, cluster_summaries, limit=cluster_limit)
    drop_triggers = _build_drop_triggers(cluster_summaries)
    primary_failure = str(data.get("primary_failure_domain") or "unknown")
    product_type = str(data.get("product_type_detected") or "")

    recommendations = _build_recommendations(
        stages=stages,
        primary_stage=primary_stage,
        cluster_drag=cluster_drag,
        overall_conversion=overall,
        primary_failure_domain=primary_failure,
    )
    recoverable = _estimate_recoverable(overall, primary_obj)
    health = _health_score(overall, stages, primary_obj)

    return FunnelDiagnosisOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        overall_conversion=round(overall, 4),
        total_agents=total_agents,
        converted_agents=converted,
        primary_bottleneck=primary_stage,
        bottleneck_severity=bottleneck_severity,
        health_score=health,
        recoverable_conversion=recoverable,
        stages=stages,
        cluster_drag=cluster_drag,
        drop_triggers=drop_triggers,
        recommendations=recommendations,
        primary_failure_domain=primary_failure,
        product_type_detected=product_type,
        signal_quality=signal_quality,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "recovery_fraction": RECOVERY_FRACTION,
            "stages_source": (
                "stage_metrics"
                if data.get("stage_metrics")
                else "stage_aggregations"
                if data.get("stage_aggregations")
                else "stage_counts"
                if data.get("stage_counts")
                else "none"
            ),
            "cluster_summaries_used": bool(cluster_summaries),
        },
    )


__all__ = [
    "FORWARD_STAGES",
    "HEALTHY_DROP_OFF",
    "STAGE_DOMAIN_MAP",
    "RECOVERY_FRACTION",
    "build_funnel_diagnosis",
]

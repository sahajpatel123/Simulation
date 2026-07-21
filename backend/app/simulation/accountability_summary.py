"""
Pure functions for filtering and summarising persisted domain_findings.

The producer side (AccountabilityEngine.generate_domain_findings) writes
the canonical ``ranked`` list onto ``simulations.results_json["domain_findings"]``
(truncated to the top 10 by ``simulation_tasks.run_full_simulation``).

This module provides two views over that list:

- ``filter_findings(raw, severity, architect, metric, limit, offset)`` —
  applies the same predicates the API exposes so the test suite can verify
  edge cases without spinning up FastAPI.

- ``build_findings_summary(raw)`` — produces a group-by rollup by severity,
  architect, cluster, metric, and recommended_action for dashboards.

Both functions are pure: same input → same output, no DB, no LLM. This keeps
them fast (the persisted list is at most 10 items) and trivially testable.
"""
from __future__ import annotations

from typing import Any

from app.schemas.accountability import (
    DomainFindingOut,
    FindingsByArchitect,
    FindingsByCluster,
    FindingsByMetric,
    FindingsSummaryOut,
    RecommendedActionCount,
    VALID_SEVERITIES,
)


DEFAULT_LIMIT: int = 10
MAX_LIMIT: int = 100


def _coerce_limit(limit: int | None) -> int:
    """Clamp to ``[1, MAX_LIMIT]`` and default to DEFAULT_LIMIT on bad input."""
    if not isinstance(limit, int):
        return DEFAULT_LIMIT
    if limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def _coerce_offset(offset: int | None) -> int:
    """Floor negative or non-int offsets to 0."""
    if not isinstance(offset, int):
        return 0
    if offset < 0:
        return 0
    return offset


def _normalise_severity(value: str | None) -> str | None:
    """
    Accept ``"critical"``, ``"CRITICAL"``, ``"WARNING"`` etc. and return
    canonical uppercase, or ``None`` when blank/invalid. Unknown values are
    treated as ``None`` (no filter applied) rather than 400'ing — the API
    surfaces 400 via a separate explicit check.
    """
    if value is None:
        return None
    candidate = value.strip().upper()
    if not candidate:
        return None
    return candidate if candidate in VALID_SEVERITIES else None


def parse_findings(raw: list[Any] | None) -> list[DomainFindingOut]:
    """
    Convert the persisted dict list into ``DomainFindingOut`` instances.

    Drops non-dict entries silently — they cannot be a finding by contract.
    """
    if not raw:
        return []
    parsed: list[DomainFindingOut] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                parsed.append(DomainFindingOut.from_raw(item))
            except Exception:
                # Skip malformed entries rather than 500 — accountability is
                # advisory; partial data is more useful than no data.
                continue
    return parsed


def filter_findings(
    raw: list[Any] | None,
    *,
    severity: str | None = None,
    architect: str | None = None,
    metric: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[DomainFindingOut]:
    """
    Apply the same predicates the API exposes. The persisted list is already
    ranked by AccountabilityEngine.rank_by_impact, so we preserve order.
    """
    findings = parse_findings(raw)
    severity_norm = _normalise_severity(severity)
    architect_norm = architect.strip().lower() if isinstance(architect, str) and architect.strip() else None
    metric_norm = metric.strip() if isinstance(metric, str) and metric.strip() else None
    effective_limit = _coerce_limit(limit)
    effective_offset = _coerce_offset(offset)

    filtered: list[DomainFindingOut] = []
    for finding in findings:
        if severity_norm and finding.severity != severity_norm:
            continue
        if architect_norm and architect_norm not in finding.architect_name.lower():
            continue
        if metric_norm and finding.metric_affected != metric_norm:
            continue
        filtered.append(finding)

    end = effective_offset + effective_limit
    return filtered[effective_offset:end]


def build_findings_summary(
    raw: list[Any] | None,
    *,
    top_n_by_group: int = 10,
    top_critical_limit: int = 5,
) -> FindingsSummaryOut:
    """
    Group the persisted findings list into a rollup suitable for dashboards.

    The producer already sorts by severity (CRITICAL first) then by impact
    descending, so we preserve that ordering when slicing the top critical
    findings and the top entries within each group.
    """
    findings = parse_findings(raw)
    if not findings:
        return FindingsSummaryOut(total_findings=0)

    # Overall severity counts.
    severity_breakdown: dict[str, int] = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for f in findings:
        bucket = f.severity if f.severity in severity_breakdown else "INFO"
        severity_breakdown[bucket] += 1

    # Roll up by architect.
    arch_agg: dict[str, dict[str, Any]] = {}
    for f in findings:
        bucket = arch_agg.setdefault(
            f.architect_name,
            {
                "finding_count": 0,
                "total_impact": 0.0,
                "severity_breakdown": {"CRITICAL": 0, "WARNING": 0, "INFO": 0},
            },
        )
        bucket["finding_count"] += 1
        bucket["total_impact"] = round(bucket["total_impact"] + f.conversion_impact, 4)
        sev_key = f.severity if f.severity in bucket["severity_breakdown"] else "INFO"
        bucket["severity_breakdown"][sev_key] += 1
    by_architect_sorted = sorted(
        arch_agg.items(), key=lambda kv: (-kv[1]["total_impact"], kv[0])
    )
    by_architect: list[FindingsByArchitect] = []
    for rank, (name, data) in enumerate(by_architect_sorted, start=1):
        by_architect.append(
            FindingsByArchitect(
                architect_name=name,
                finding_count=data["finding_count"],
                total_impact=round(data["total_impact"], 4),
                severity_breakdown=dict(data["severity_breakdown"]),
                rank=rank,
            )
        )

    # Roll up by cluster (top_n_by_group).
    cluster_agg: dict[str, dict[str, Any]] = {}
    for f in findings:
        bucket = cluster_agg.setdefault(
            f.cluster_id,
            {
                "cluster_name": f.cluster_name,
                "finding_count": 0,
                "total_impact": 0.0,
                "severity_breakdown": {"CRITICAL": 0, "WARNING": 0, "INFO": 0},
            },
        )
        bucket["finding_count"] += 1
        bucket["total_impact"] = round(bucket["total_impact"] + f.conversion_impact, 4)
        sev_key = f.severity if f.severity in bucket["severity_breakdown"] else "INFO"
        bucket["severity_breakdown"][sev_key] += 1
    by_cluster_sorted = sorted(
        cluster_agg.items(),
        key=lambda kv: (-kv[1]["total_impact"], kv[1]["cluster_name"]),
    )[:top_n_by_group]
    by_cluster: list[FindingsByCluster] = [
        FindingsByCluster(
            cluster_id=cid,
            cluster_name=data["cluster_name"],
            finding_count=data["finding_count"],
            total_impact=round(data["total_impact"], 4),
            severity_breakdown=dict(data["severity_breakdown"]),
        )
        for cid, data in by_cluster_sorted
    ]

    # Roll up by metric (top_n_by_group).
    metric_agg: dict[str, dict[str, Any]] = {}
    for f in findings:
        bucket = metric_agg.setdefault(
            f.metric_affected,
            {
                "finding_count": 0,
                "total_impact": 0.0,
                "severity_breakdown": {"CRITICAL": 0, "WARNING": 0, "INFO": 0},
            },
        )
        bucket["finding_count"] += 1
        bucket["total_impact"] = round(bucket["total_impact"] + f.conversion_impact, 4)
        sev_key = f.severity if f.severity in bucket["severity_breakdown"] else "INFO"
        bucket["severity_breakdown"][sev_key] += 1
    by_metric_sorted = sorted(
        metric_agg.items(), key=lambda kv: (-kv[1]["total_impact"], kv[0])
    )[:top_n_by_group]
    by_metric: list[FindingsByMetric] = [
        FindingsByMetric(
            metric_affected=metric_name,
            finding_count=data["finding_count"],
            total_impact=round(data["total_impact"], 4),
            severity_breakdown=dict(data["severity_breakdown"]),
        )
        for metric_name, data in by_metric_sorted
    ]

    # Recommended-action frequency (top_n_by_group).
    action_agg: dict[str, dict[str, Any]] = {}
    for f in findings:
        bucket = action_agg.setdefault(
            f.recommended_action,
            {"count": 0, "total_impact": 0.0},
        )
        bucket["count"] += 1
        bucket["total_impact"] = round(bucket["total_impact"] + f.conversion_impact, 4)
    actions_sorted = sorted(
        action_agg.items(),
        key=lambda kv: (-kv[1]["count"], -kv[1]["total_impact"], kv[0]),
    )[:top_n_by_group]
    recommended_actions: list[RecommendedActionCount] = [
        RecommendedActionCount(
            recommended_action=action,
            count=data["count"],
            total_impact=round(data["total_impact"], 4),
        )
        for action, data in actions_sorted
    ]

    # Top CRITICAL findings (preserve ranked order; findings are already sorted
    # CRITICAL → WARNING → INFO at producer time, so we just take the prefix).
    top_critical_findings: list[DomainFindingOut] = [
        f for f in findings if f.severity == "CRITICAL"
    ][: max(0, top_critical_limit)]

    return FindingsSummaryOut(
        total_findings=len(findings),
        severity_breakdown=severity_breakdown,
        by_architect=by_architect,
        by_cluster=by_cluster,
        by_metric=by_metric,
        recommended_actions=recommended_actions,
        top_critical_findings=top_critical_findings,
    )


__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "parse_findings",
    "filter_findings",
    "build_findings_summary",
]

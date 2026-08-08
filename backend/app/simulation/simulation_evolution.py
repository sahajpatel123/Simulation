"""Pure run-to-run evolution digest for one project.

Complements the raw ``sim-diff`` / ``compare`` endpoints with a focused,
project-scoped view: "did the latest simulation improve things?" Given the
two most recent completed runs, this module emits:

* conversion movement (previous → latest, delta + direction),
* critical findings added / resolved between the runs,
* bottleneck-stage movement (excess drop-off vs the healthy Markov model),
* a short founder narrative,
* the latest run's top domain recommendations.

The module is pure-Python (no SQL, no I/O) and follows the same
deterministic helper style as ``simulation_trend`` and ``sim_diff``.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.simulation_evolution import (
    EvolutionBottleneck,
    EvolutionConversion,
    EvolutionFinding,
    EvolutionRecommendation,
    EvolutionRun,
    EvolutionSummary,
    SimulationEvolutionOut,
)

# Healthy drop-off rates derived from the base Markov transition matrix
# (see app.simulation.markov). Used to identify the funnel bottleneck when
# stage metrics are present in the persisted payload.
HEALTHY_DROP_OFF: dict[str, float] = {
    "ARRIVE": 0.13,
    "BROWSE": 0.38,
    "CONSIDER": 0.38,
    "DECIDE": 0.55,
    "PURCHASE": 0.0,
    "ABANDON": 0.0,
    "RETURN": 0.20,
}

FORWARD_STAGES: tuple[str, ...] = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE")

MAX_RECOMMENDATIONS: int = 3
DELTA_EPSILON: float = 0.001


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coalesce_number(*values: Any) -> float | None:
    """Return the first parseable number, treating ``0`` as a valid value."""
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json as _json

        try:
            parsed = _json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _sort_key(row: dict[str, Any]) -> tuple[str, int]:
    created_at = row.get("created_at")
    if hasattr(created_at, "isoformat"):
        try:
            if getattr(created_at, "tzinfo", None) is None:
                created_at = created_at.replace(tzinfo=UTC)
            else:
                created_at = created_at.astimezone(UTC)
            return (created_at.isoformat(), _safe_int(row.get("id")))
        except Exception:
            pass
    return (str(created_at or ""), _safe_int(row.get("id")))


def _conversion_rate(results: dict[str, Any]) -> float | None:
    return _coalesce_number(
        results.get("population_weighted_conversion"),
        results.get("conversion_rate"),
        results.get("mean_conversion_rate"),
    )


def _critical_findings(results: dict[str, Any]) -> list[dict[str, Any]]:
    raw = results.get("domain_findings") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or item.get("level") or "INFO").upper()
        if severity == "CRITICAL":
            out.append(item)
    return out


def _finding_key(item: dict[str, Any]) -> str:
    domain = str(item.get("architect_name") or item.get("domain") or "").casefold()
    metric = str(item.get("metric_affected") or item.get("metric") or "").casefold()
    return f"{domain}:{metric}"


def _finding_summary(item: dict[str, Any]) -> str:
    return str(
        item.get("finding")
        or item.get("summary")
        or item.get("recommended_action")
        or ""
    )


def _bottleneck_stage(results: dict[str, Any]) -> str | None:
    raw = (
        results.get("stage_metrics")
        or results.get("stage_aggregations")
        or []
    )
    if not isinstance(raw, list):
        return None
    rows: list[tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("state") or item.get("stage") or "").upper().strip()
        if not stage or stage not in FORWARD_STAGES:
            continue
        drop = _coalesce_number(
            item.get("drop_off_rate"),
            item.get("mean_drop_off_rate"),
        )
        if drop is None:
            continue
        healthy = HEALTHY_DROP_OFF.get(stage, 0.35)
        rows.append((stage, drop - healthy))
    if not rows:
        return None
    return max(rows, key=lambda pair: pair[1])[0]


def _top_recommendations(results: dict[str, Any]) -> list[EvolutionRecommendation]:
    raw = results.get("domain_findings") or []
    if not isinstance(raw, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        impact = _coalesce_number(
            item.get("conversion_impact"),
            item.get("impact_on_overall_conversion"),
        ) or 0.0
        parsed.append(
            {
                "impact": impact,
                "domain": str(item.get("architect_name") or item.get("domain") or ""),
                "metric": str(item.get("metric_affected") or item.get("metric") or ""),
                "severity": str(item.get("severity") or "INFO").upper(),
                "summary": _finding_summary(item),
            }
        )
    parsed.sort(
        key=lambda item: (
            -1 if item["severity"] == "CRITICAL" else 0,
            -item["impact"],
            item["domain"],
        )
    )
    return [
        EvolutionRecommendation(
            priority=idx + 1,
            title=(item["metric"].replace("_", " ").title() or item["domain"]),
            summary=item["summary"],
            domain=item["domain"],
            source="DOMAIN_FINDING",
            severity=item["severity"],
        )
        for idx, item in enumerate(parsed[:MAX_RECOMMENDATIONS])
    ]


def _classify_delta(delta: float | None) -> str:
    if delta is None:
        return "NO_DATA"
    if delta > DELTA_EPSILON:
        return "IMPROVED"
    if delta < -DELTA_EPSILON:
        return "WORSENED"
    return "STABLE"


def _build_narrative(
    previous: EvolutionRun,
    latest: EvolutionRun,
    conversion: EvolutionConversion,
    findings: list[EvolutionFinding],
    bottleneck: EvolutionBottleneck,
) -> tuple[str, str]:
    direction = conversion.direction
    if direction == "NO_DATA":
        return "NO_DATA", (
            "Could not compute a conversion comparison — one or both runs "
            "are missing conversion-rate data."
        )

    delta = conversion.delta
    delta_txt = f"{delta:+.1%}" if delta is not None else "unknown"
    prev_txt = f"{conversion.previous:.1%}" if conversion.previous is not None else "n/a"
    latest_txt = f"{conversion.latest:.1%}" if conversion.latest is not None else "n/a"

    if direction == "STABLE":
        headline = (
            f"Latest sim conversion stayed stable at {latest_txt} "
            f"({delta_txt} vs {prev_txt})."
        )
    else:
        headline = (
            f"Latest sim conversion {direction.lower()} to "
            f"{latest_txt} ({delta_txt} vs {prev_txt})."
        )

    sentences: list[str] = [headline]
    if findings:
        added = [f for f in findings if f.direction == "ADDED"]
        resolved = [f for f in findings if f.direction == "RESOLVED"]
        if resolved:
            sentences.append(
                f"{len(resolved)} critical finding(s) resolved since the "
                "previous run."
            )
        if added:
            sentences.append(
                f"{len(added)} new critical finding(s) surfaced in the "
                "latest run."
            )
    if bottleneck.changed:
        sentences.append(
            f"Primary bottleneck moved from {bottleneck.previous or 'unknown'} "
            f"to {bottleneck.latest or 'unknown'}."
        )

    return headline, " ".join(sentences)


def build_simulation_evolution(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
) -> dict[str, Any]:
    """Compute the run-to-run evolution digest for a project.

    ``rows`` shape (caller may pass in either order; the two most recent
    completed runs by ``created_at`` are used)::

        [
          {
            "id": int,
            "status": str,
            "signal_quality": float | None,
            "results_json": dict | None,
            "created_at": "...",
          },
          ...
        ]
    """
    completed = [
        row for row in (rows or []) if str(row.get("status") or "").upper() == "COMPLETED"
    ]
    completed.sort(key=_sort_key)
    if len(completed) < 2:
        return SimulationEvolutionOut(
            project_id=project_id,
            previous_run=None,
            latest_run=None,
            conversion=EvolutionConversion(),
            critical_findings=[],
            bottleneck=EvolutionBottleneck(),
            summary=EvolutionSummary(),
            recommendations=[],
            generated_at=datetime.now(UTC).isoformat(),
        ).model_dump()

    previous_row, latest_row = completed[-2], completed[-1]
    previous_results = _coerce_results(previous_row.get("results_json"))
    latest_results = _coerce_results(latest_row.get("results_json"))

    previous_run = EvolutionRun(
        simulation_id=_safe_int(previous_row.get("id")),
        status="COMPLETED",
        signal_quality=_safe_float(previous_row.get("signal_quality")),
        conversion_rate=_conversion_rate(previous_results),
        critical_finding_count=len(_critical_findings(previous_results)),
        bottleneck_stage=_bottleneck_stage(previous_results),
        created_at=_iso(previous_row.get("created_at")),
    )
    latest_run = EvolutionRun(
        simulation_id=_safe_int(latest_row.get("id")),
        status="COMPLETED",
        signal_quality=_safe_float(latest_row.get("signal_quality")),
        conversion_rate=_conversion_rate(latest_results),
        critical_finding_count=len(_critical_findings(latest_results)),
        bottleneck_stage=_bottleneck_stage(latest_results),
        created_at=_iso(latest_row.get("created_at")),
    )

    delta = (
        round(latest_run.conversion_rate - previous_run.conversion_rate, 6)
        if latest_run.conversion_rate is not None and previous_run.conversion_rate is not None
        else None
    )
    conversion = EvolutionConversion(
        previous=previous_run.conversion_rate,
        latest=latest_run.conversion_rate,
        delta=delta,
        direction=_classify_delta(delta),
    )

    prev_critical = {
        _finding_key(item): item for item in _critical_findings(previous_results)
    }
    latest_critical = {
        _finding_key(item): item for item in _critical_findings(latest_results)
    }

    findings: list[EvolutionFinding] = []
    for key in sorted(set(latest_critical) - set(prev_critical)):
        item = latest_critical[key]
        findings.append(
            EvolutionFinding(
                domain=str(item.get("architect_name") or item.get("domain") or ""),
                metric_affected=str(
                    item.get("metric_affected") or item.get("metric") or ""
                ),
                severity="CRITICAL",
                direction="ADDED",
                summary=_finding_summary(item),
            )
        )
    for key in sorted(set(prev_critical) - set(latest_critical)):
        item = prev_critical[key]
        findings.append(
            EvolutionFinding(
                domain=str(item.get("architect_name") or item.get("domain") or ""),
                metric_affected=str(
                    item.get("metric_affected") or item.get("metric") or ""
                ),
                severity="CRITICAL",
                direction="RESOLVED",
                summary=_finding_summary(item),
            )
        )

    bottleneck = EvolutionBottleneck(
        previous=previous_run.bottleneck_stage,
        latest=latest_run.bottleneck_stage,
        changed=(
            previous_run.bottleneck_stage != latest_run.bottleneck_stage
            and latest_run.bottleneck_stage is not None
        ),
    )

    headline, narrative = _build_narrative(
        previous_run,
        latest_run,
        conversion,
        findings,
        bottleneck,
    )
    summary = EvolutionSummary(
        verdict=conversion.direction,
        headline=headline,
        narrative=narrative,
    )

    return SimulationEvolutionOut(
        project_id=project_id,
        previous_run=previous_run,
        latest_run=latest_run,
        conversion=conversion,
        critical_findings=findings,
        bottleneck=bottleneck,
        summary=summary,
        recommendations=_top_recommendations(latest_results),
        generated_at=datetime.now(UTC).isoformat(),
    ).model_dump()


__all__ = ["build_simulation_evolution"]

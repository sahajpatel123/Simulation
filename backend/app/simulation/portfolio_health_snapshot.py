"""Pure helpers for the per-user portfolio-health-snapshot endpoint.

Composes a single 0-100 portfolio health rollup across
all of the user's projects, so the dashboard header can
surface one big number without fanning out to every
per-project /projects/{id}/health endpoint.

The helper is pure-Python. The route layer pulls the
list of per-project health payloads and hands them to
:func:`build_portfolio_health_snapshot`.

What it answers
--------------
* "How healthy is my portfolio overall?"
* "Should I be concerned about my health score?"
* "What should I focus on first?"

Output shape
------------
::

    {
      "project_count": int,
      "portfolio_health_score": int,    # 0..100
      "verdict": "HEALTHY" | "NEEDS_ATTENTION" | "AT_RISK",
      "average_score": float,
      "lowest_project_score": int | None,
      "health_trend": "IMPROVING" | "DECLINING" | "STABLE" | None,
      "improvement_opportunities": list[str],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Score bands.
HEALTHY_MIN: int = 70
AT_RISK_MAX: int = 40

VERDICT_HEALTHY: str = "HEALTHY"
VERDICT_NEEDS_ATTENTION: str = "NEEDS_ATTENTION"
VERDICT_AT_RISK: str = "AT_RISK"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _classify_verdict(score: int) -> str:
    if score >= HEALTHY_MIN:
        return VERDICT_HEALTHY
    if score <= AT_RISK_MAX:
        return VERDICT_AT_RISK
    return VERDICT_NEEDS_ATTENTION


def _verdict_severity(verdict: str) -> str:
    if verdict == VERDICT_HEALTHY:
        return SIGNAL_OK
    if verdict == VERDICT_AT_RISK:
        return SIGNAL_CRITICAL
    return SIGNAL_WATCH


def build_portfolio_health_snapshot(
    project_health_payloads: list[dict] | None = None,
    previous_average_score: float | None = None,
) -> dict:
    """Compose the per-user portfolio-health-snapshot.

    Args:
        project_health_payloads: list of per-project
            ``/projects/{id}/health`` payloads. Each entry
            must expose ``project_health_score``.
        previous_average_score: optional previous period's
            average score for trend detection.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    scores: list[int] = []
    for entry in project_health_payloads or []:
        if not isinstance(entry, dict):
            continue
        score = _safe_int(entry.get("project_health_score"))
        if score > 0:  # skip zero scores (likely missing)
            scores.append(score)

    project_count = len(scores)
    average_score = (
        round(sum(scores) / len(scores)) if scores else 0
    )
    lowest_project_score = min(scores) if scores else None

    # ---- Trend detection ------------------------------------------
    health_trend = None
    if previous_average_score is not None:
        if average_score > previous_average_score + 5:
            health_trend = "IMPROVING"
        elif average_score < previous_average_score - 5:
            health_trend = "DECLINING"
        else:
            health_trend = "STABLE"

    # ---- Improvement opportunities ---------------------------------
    improvement_opportunities: list[str] = []
    if scores:
        low_scoring = sum(1 for s in scores if s < 50)
        if low_scoring > 0:
            improvement_opportunities.append(
                f"{low_scoring} project(s) have health < 50 — prioritize improvements"
            )
        critical_issues = sum(1 for s in scores if s < 40)
        if critical_issues > 0:
            improvement_opportunities.append(
                f"{critical_issues} project(s) at risk — address immediately"
            )
    if average_score < 70 and project_count > 0:
        # Find biggest gaps
        gaps = [70 - s for s in scores if s < 70]
        if gaps:
            avg_gap = round(sum(gaps) / len(gaps))
            improvement_opportunities.append(
                f"Average gap to healthy: {avg_gap} points"
            )

    verdict = _classify_verdict(average_score)
    severity = _verdict_severity(verdict)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "portfolio_health_score",
        "value": average_score,
        "severity": severity,
        "display": f"Portfolio health: {average_score}/100",
    })
    if health_trend:
        trend_severity = SIGNAL_OK if health_trend == "IMPROVING" else (
            SIGNAL_CRITICAL if health_trend == "DECLINING" else SIGNAL_WATCH
        )
        key_signals.append({
            "label": "health_trend",
            "value": health_trend,
            "severity": trend_severity,
            "display": f"Trend: {health_trend.lower()}",
        })
    if project_count > 0:
        key_signals.append({
            "label": "project_count",
            "value": project_count,
            "severity": SIGNAL_OK,
            "display": f"{project_count} project(s) in portfolio",
        })
    if improvement_opportunities:
        key_signals.append({
            "label": "improvement_opportunities",
            "value": len(improvement_opportunities),
            "severity": SIGNAL_WATCH,
            "display": improvement_opportunities[0],
        })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if project_count == 0:
        sentences.append(
            "No projects on file yet — portfolio health "
            "is not yet applicable."
        )
    else:
        verdict_text = verdict.replace('_', ' ').lower()
        if health_trend:
            trend_word = "improving" if health_trend == "IMPROVING" else (
                "declining" if health_trend == "DECLINING" else "stable"
            )
            sentences.append(
                f"{project_count} project(s); portfolio health "
                f"{average_score}/100 ({verdict_text}, {trend_word})."
            )
        else:
            sentences.append(
                f"{project_count} project(s); portfolio health "
                f"{average_score}/100 ({verdict_text})."
            )
        if lowest_project_score is not None and lowest_project_score < 50:
            sentences.append(
                f"Worst project is at {lowest_project_score}/100."
            )
        if improvement_opportunities:
            sentences.append(
                f"Focus: {'; '.join(improvement_opportunities[:2])}."
            )
    narrative = " ".join(sentences)

    return {
        "project_count": project_count,
        "portfolio_health_score": average_score,
        "verdict": verdict,
        "average_score": float(average_score),
        "lowest_project_score": lowest_project_score,
        "health_trend": health_trend,
        "improvement_opportunities": improvement_opportunities,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "HEALTHY_MIN",
    "AT_RISK_MAX",
    "VERDICT_HEALTHY",
    "VERDICT_NEEDS_ATTENTION",
    "VERDICT_AT_RISK",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_portfolio_health_snapshot",
]  # noqa: E501

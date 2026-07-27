"""Pure helpers for the per-user insights endpoint.

Composes a single "executive summary" payload: a list
of 2-3 short insight sentences plus a one-line headline,
synthesized from the existing user-level digests (dashes
in users.py + portfolio-health-snapshot + weekly-digest).

The helper is pure-Python. The route layer pulls the
count + verdict + headline and hands them to
:func:`build_insights`.

Output shape
------------
::

    {
      "has_data": bool,
      "headline": str,
      "insights": list[str],
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_insights(
    project_count: int = 0,
    sim_count_total: int = 0,
    decision_count_total: int = 0,
    outcome_count_total: int = 0,
    portfolio_verdict: str = "AT_RISK",
    portfolio_score: int = 0,
    weekly_sim_count: int = 0,
    weekly_decision_count: int = 0,
    weekly_outcome_count: int = 0,
    needs_attention_count: int = 0,
) -> dict:
    """Compose the per-user insights digest.

    Args:
        project_count: total owned projects.
        sim_count_total / decision_count_total /
        outcome_count_total: lifetime counts.
        portfolio_verdict / portfolio_score: from
            /me/portfolio-health-snapshot.
        weekly_sim_count / weekly_decision_count /
        weekly_outcome_count: from /me/weekly-digest.
        needs_attention_count: from /me/projects-by-status
            (actionable bucket).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    project_count = _safe_int(project_count)
    sim_count_total = _safe_int(sim_count_total)
    decision_count_total = _safe_int(decision_count_total)
    outcome_count_total = _safe_int(outcome_count_total)
    weekly_sim_count = _safe_int(weekly_sim_count)
    weekly_decision_count = _safe_int(weekly_decision_count)
    weekly_outcome_count = _safe_int(weekly_outcome_count)
    needs_attention_count = _safe_int(needs_attention_count)
    portfolio_score = _safe_int(portfolio_score)

    has_data = (
        project_count > 0
        or sim_count_total > 0
        or decision_count_total > 0
        or outcome_count_total > 0
    )

    insights: list[str] = []
    if project_count == 0:
        insights.append("No projects yet - create one to get started.")
    if sim_count_total > 0 and project_count > 0:
        sim_per_project = round(sim_count_total / project_count, 1)
        insights.append(
            f"Across {project_count} project(s): "
            f"{sim_count_total} sim(s) ({sim_per_project} per project), "
            f"{decision_count_total} decision(s), "
            f"{outcome_count_total} outcome(s)."
        )
    if weekly_sim_count + weekly_decision_count + weekly_outcome_count > 0:
        insights.append(
            f"Last 7 days: {weekly_sim_count} sim(s), "
            f"{weekly_decision_count} decision(s), "
            f"{weekly_outcome_count} outcome(s)."
        )
    if needs_attention_count:
        insights.append(
            f"{needs_attention_count} project(s) need attention."
        )
    if portfolio_score > 0:
        insights.append(
            f"Portfolio health: {portfolio_score}/100 "
            f"({portfolio_verdict.lower().replace('_', ' ')})."
        )

    # Headline.
    if not has_data:
        headline = "Welcome - run your first sim to get insights."
    elif needs_attention_count:
        headline = (
            f"{needs_attention_count} project(s) need your attention."
        )
    elif portfolio_verdict == "AT_RISK":
        headline = "Portfolio health is at risk - review the digests."
    elif portfolio_verdict == "NEEDS_ATTENTION":
        headline = "Portfolio health needs attention - keep going."
    elif portfolio_verdict == "HEALTHY":
        headline = "Portfolio is healthy - great work!"
    else:
        headline = "Portfolio health is good - room to grow."

    severity = (
        SIGNAL_CRITICAL
        if needs_attention_count >= 3
        else SIGNAL_WATCH
        if needs_attention_count > 0
        else SIGNAL_OK
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "headline",
        "value": headline,
        "severity": severity,
        "display": headline,
    })

    # ---- Narrative ------------------------------------------------
    if not has_data:
        narrative = "No activity yet - start a sim to get insights."
    else:
        narrative = " | ".join(insights)

    return {
        "has_data": has_data,
        "headline": headline,
        "insights": insights,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_insights",
]  # noqa: E501
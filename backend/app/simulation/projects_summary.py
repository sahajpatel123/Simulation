"""Pure helpers for the per-user projects summary digest.

Composes a lightweight per-project summary (just the
fields the dashboard grid needs) so the projects-list
view can render one row per project without pulling
the full ProjectOut payloads.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls a flat list of project-summary dicts and
hands them to :func:`build_projects_summary`.

What it answers
--------------
* "Which projects have been active recently?"
* "Which projects are ready for attention?"
* "Where are the biggest conversion bottlenecks?"

Output shape
------------
::

    {
      "project_count": int,
      "projects": [
        {
          "id": int,
          "title": str,
          "status": str,
          "brief_completed": bool,
          "latest_sim_conversion_rate": float | None,
          "latest_sim_status": str | None,
          "latest_sim_top_dropoff_stage": str | None,
          "sim_count": int,
          "decision_count": int,
          "outcome_count": int,
        },
        ...
      ],
      "portfolio_health_score": float,
      "needs_attention_count": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import datetime, timezone

MAX_PROJECTS: int = 50

SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def build_projects_summary(
    project_summaries: list[dict] | None,
    now: object | None = None,
    portfolio_health_score: float | None = None,
) -> dict:
    """Compose the per-user projects-summary digest.

    Args:
        project_summaries: list of pre-flattened per-project
            summary dicts. Each entry MUST expose ``id``;
            the helper is permissive about the rest.
        now: optional reference time (kept for shape
            symmetry with other digests - currently unused).
        portfolio_health_score: optional health score (0-100)
            from portfolio health snapshot.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    rows: list[dict] = []
    for raw in project_summaries or []:
        if not isinstance(raw, dict):
            continue
        rows.append({
            "id": raw.get("id"),
            "title": raw.get("title"),
            "status": raw.get("status") or "UNKNOWN",
            "brief_completed": bool(raw.get("brief_completed")),
            "latest_sim_conversion_rate": _safe_float(
                raw.get("latest_sim_conversion_rate"),
            ),
            "latest_sim_status": raw.get("latest_sim_status"),
            "latest_sim_top_dropoff_stage": raw.get("top_dropoff_stage"),
            "sim_count": _safe_int(raw.get("sim_count")),
            "decision_count": _safe_int(raw.get("decision_count")),
            "outcome_count": _safe_int(raw.get("outcome_count")),
        })

    capped = rows[:MAX_PROJECTS]
    project_count = len(capped)

    # ---- Aggregates -------------------------------------------------
    sim_count_total = sum(r["sim_count"] for r in capped)
    decision_count_total = sum(r["decision_count"] for r in capped)
    outcome_count_total = sum(r["outcome_count"] for r in capped)
    with_brief = sum(
        1 for r in capped if r["brief_completed"]
    )

    # ---- Projects needing attention ---------------------------------
    # PENDING status + brief not completed OR low conversion rates
    needs_attention_count = 0
    for r in capped:
        status = r.get("status", "")
        brief_done = r.get("brief_completed", False)
        conv_rate = r.get("latest_sim_conversion_rate")
        # Flag: PENDING without brief, or conversion < 5%
        if status == "PENDING" and not brief_done:
            needs_attention_count += 1
        elif conv_rate is not None and conv_rate < 0.05:
            needs_attention_count += 1

    # ---- Key signals -----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "project_count",
        "value": project_count,
        "severity": (
            SIGNAL_WATCH if project_count == 0 else SIGNAL_OK
        ),
        "display": f"{project_count} project(s) on file",
    })
    if sim_count_total > 0:
        key_signals.append({
            "label": "sim_count_total",
            "value": sim_count_total,
            "severity": (
                SIGNAL_OK if sim_count_total >= 5
                else SIGNAL_WATCH if sim_count_total >= 1
                else SIGNAL_OK
            ),
            "display": (
                f"{sim_count_total} sim(s) across "
                f"all projects"
            ),
        })
    if needs_attention_count > 0:
        key_signals.append({
            "label": "needs_attention_count",
            "value": needs_attention_count,
            "severity": SIGNAL_WATCH,
            "display": (
                f"{needs_attention_count} project(s) need attention"
            ),
        })
    if portfolio_health_score is not None:
        score = round(portfolio_health_score)
        if score >= 70:
            severity = SIGNAL_OK
        elif score >= 40:
            severity = SIGNAL_WATCH
        else:
            severity = SIGNAL_CRITICAL
        key_signals.append({
            "label": "portfolio_health_score",
            "value": score,
            "severity": severity,
            "display": f"Portfolio health: {score}/100",
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    if project_count == 0:
        sentences.append("No projects on file yet.")
    else:
        sentences.append(
            f"{project_count} project(s); "
            f"{with_brief} have a complete brief."
        )
    if sim_count_total:
        sentences.append(
            f"{sim_count_total} sim(s), "
            f"{decision_count_total} decision(s), "
            f"{outcome_count_total} outcome(s) across "
            f"the portfolio."
        )
    if needs_attention_count > 0:
        sentences.append(
            f"{needs_attention_count} project(s) need attention."
        )
    if portfolio_health_score is not None:
        score = round(portfolio_health_score)
        sentences.append(f"Portfolio health score: {score}/100.")
    narrative = " ".join(sentences)

    return {
        "project_count": project_count,
        "projects": capped,
        "sim_count_total": sim_count_total,
        "decision_count_total": decision_count_total,
        "outcome_count_total": outcome_count_total,
        "portfolio_health_score": portfolio_health_score or 0.0,
        "needs_attention_count": needs_attention_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


__all__ = [
    "MAX_PROJECTS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_projects_summary",
]  # noqa: E501

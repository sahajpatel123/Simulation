"""Pure helpers for the per-user projects summary digest.

Composes a lightweight per-project summary (just the
fields the dashboard grid needs) so the projects-list
view can render one row per project without pulling
the full ProjectOut payloads.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls a flat list of project-summary dicts and
hands them to :func:`build_projects_summary`.

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
          "sim_count": int,
          "decision_count": int,
          "outcome_count": int,
        },
        ...
      ],
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
) -> dict:
    """Compose the per-user projects-summary digest.

    Args:
        project_summaries: list of pre-flattened per-project
            summary dicts. Each entry MUST expose ``id``;
            the helper is permissive about the rest.
        now: optional reference time (kept for shape
            symmetry with other digests - currently unused).

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
            "latest_sim_created_at": _iso_or_none(
                raw.get("latest_sim_created_at"),
            ),
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
    narrative = " ".join(sentences)

    return {
        "project_count": project_count,
        "projects": capped,
        "sim_count_total": sim_count_total,
        "decision_count_total": decision_count_total,
        "outcome_count_total": outcome_count_total,
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

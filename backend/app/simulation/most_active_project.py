"""Pure helpers for the per-user most-active-project endpoint.

Composes a single "where should I focus?" recommendation:
the project with the most total activity (sims +
decisions + outcomes) in the last 7 days.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the rolling-7-day counts and hands the
list of (project_id, project_title, total) tuples to
:func:`build_most_active_project`.

Output shape
------------
::

    {
      "has_activity": bool,
      "project_id": int | None,
      "project_title": str | None,
      "total_actions_7d": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_most_active_project(
    project_activity: list[tuple] | None = None,
) -> dict:
    """Compose the most-active-project digest.

    Args:
        project_activity: list of tuples. Each entry
            MUST expose ``project_id`` and
            ``project_title`` plus a numeric total.
            Accepts:
            - ``(project_id, project_title, total)``
            - ``(project_id, project_title, sim_count,
              decision_count, outcome_count)`` (sum
              computed inside the helper)

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    best: dict | None = None
    best_total = 0
    for entry in project_activity or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        project_id = entry[0]
        project_title = entry[1]
        if len(entry) == 3:
            total = _safe_int(entry[2])
        else:
            total = (
                _safe_int(entry[2])
                + _safe_int(entry[3])
                + _safe_int(entry[4])
            )
        if total > best_total:
            best_total = total
            best = {
                "project_id": project_id,
                "project_title": project_title,
                "total_actions_7d": total,
            }

    has_activity = best is not None and best_total > 0
    project_id = best["project_id"] if best else None
    project_title = best["project_title"] if best else None

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "has_activity",
        "value": has_activity,
        "severity": (
            SIGNAL_OK if has_activity else SIGNAL_WATCH
        ),
        "display": (
            f"Most-active project: {project_title}"
            if has_activity
            else "No activity in the last 7 days"
        ),
    })
    if has_activity:
        key_signals.append({
            "label": "total_actions_7d",
            "value": best_total,
            "severity": (
                SIGNAL_OK if best_total >= 3 else SIGNAL_WATCH
            ),
            "display": f"{best_total} action(s) in the last 7 days",
        })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if not has_activity:
        sentences.append(
            "No sims, decisions, or outcomes in the last 7 days."
        )
    else:
        sentences.append(
            f"Most-active project: '{project_title}' "
            f"({best_total} action(s) in the last 7 days)."
        )
    narrative = " ".join(sentences)

    return {
        "has_activity": has_activity,
        "project_id": project_id,
        "project_title": project_title,
        "total_actions_7d": best_total,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_most_active_project",
]  # noqa: E501

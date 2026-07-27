"""Pure helpers for the per-user projects-by-status endpoint.

Composes a single status-bucket count dict so the
dashboard's projects-by-status pie chart can render one
payload.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the (status, count) tuples and hands them
to :func:`build_projects_by_status`.

Output shape
------------
::

    {
      "project_count": int,
      "status_breakdown": {"COMPLETE": 3, "BRIEF": 1, ...},
      "most_common_status": str | None,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Statuses the founder should act on (vs stable/finished
# states).
ACTIONABLE_STATUSES: frozenset[str] = frozenset({
    "RUNNING", "PENDING",
})


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_projects_by_status(
    status_counts: list[tuple[str, int]] | None = None,
) -> dict:
    """Compose the per-user projects-by-status digest.

    Args:
        status_counts: list of ``(status, count)`` tuples
            from the route layer.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    breakdown: dict[str, int] = {}
    for entry in status_counts or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        status = entry[0]
        count = _safe_int(entry[1])
        if not isinstance(status, str) or not status:
            continue
        breakdown[status] = breakdown.get(status, 0) + count

    project_count = sum(breakdown.values())
    most_common: str | None = None
    if breakdown:
        most_common = max(breakdown.items(), key=lambda kv: kv[1])[0]

    actionable_count = sum(
        count for status, count in breakdown.items()
        if status in ACTIONABLE_STATUSES
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "project_count",
        "value": project_count,
        "severity": (
            SIGNAL_WATCH if project_count == 0 else SIGNAL_OK
        ),
        "display": f"{project_count} project(s) on file",
    })
    if actionable_count:
        key_signals.append({
            "label": "actionable_count",
            "value": actionable_count,
            "severity": (
                SIGNAL_CRITICAL if actionable_count >= 3
                else SIGNAL_WATCH
            ),
            "display": (
                f"{actionable_count} project(s) running or pending"
            ),
        })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if project_count == 0:
        sentences.append("No projects on file yet.")
    else:
        sentences.append(
            f"{project_count} project(s); "
            f"most common status: {most_common}."
        )
        if actionable_count:
            sentences.append(
                f"{actionable_count} project(s) still "
                f"running or pending."
            )
    narrative = " ".join(sentences)

    return {
        "project_count": project_count,
        "status_breakdown": breakdown,
        "most_common_status": most_common,
        "actionable_count": actionable_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "ACTIONABLE_STATUSES",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_projects_by_status",
]  # noqa: E501

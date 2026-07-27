"""Pure helpers for the per-user most-active-weekday endpoint.

Composes a single "what day of the week are you most
active?" payload so the dashboard can show a personal
schedule insight.

The helper is pure-Python. The route layer builds a
list of weekday actions (Mon=0..Sun=6) and hands them
to :func:`build_most_active_weekday`.

Output shape
------------
::

    {
      "total_actions": int,
      "most_active_weekday": int | None,
      "most_active_count": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

WEEKDAY_NAMES: tuple[str, ...] = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_most_active_weekday(
    weekday_actions: list[int] | None = None,
) -> dict:
    """Compose the per-user most-active-weekday digest.

    Args:
        weekday_actions: list of weekday ints (0-6, with
            0=Monday and 6=Sunday) representing the user's
            sim / decision / outcome activity.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    weekday_actions = weekday_actions or []
    weekday_counts: dict[int, int] = {}
    for wd in weekday_actions:
        if not isinstance(wd, int):
            continue
        if wd < 0 or wd > 6:
            continue
        weekday_counts[wd] = weekday_counts.get(wd, 0) + 1

    total_actions = sum(weekday_counts.values())
    most_active_weekday = None
    most_active_count = 0
    if weekday_counts:
        most_active_weekday = max(
            weekday_counts,
            key=weekday_counts.get,
        )
        most_active_count = weekday_counts[most_active_weekday]

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if total_actions > 0:
        key_signals.append({
            "label": "most_active_weekday",
            "value": most_active_weekday,
            "severity": (
                SIGNAL_OK if most_active_count >= 5
                else SIGNAL_WATCH
            ),
            "display": (
                f"Most active: "
                f"{WEEKDAY_NAMES[most_active_weekday]}"
                if most_active_weekday is not None
                else ""
            ),
        })

    # ---- Narrative ------------------------------------------------
    if total_actions == 0:
        narrative = (
            "No sim/decision/outcome activity yet - run a "
            "few to populate this tile."
        )
    elif most_active_weekday is None:
        narrative = (
            f"{total_actions} action(s) - no valid weekday "
            f"data."
        )
    else:
        narrative = (
            f"Most active day: "
            f"{WEEKDAY_NAMES[most_active_weekday]} "
            f"({most_active_count} action(s) of "
            f"{total_actions} total)."
        )

    return {
        "total_actions": total_actions,
        "most_active_weekday": most_active_weekday,
        "most_active_count": most_active_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "WEEKDAY_NAMES",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_most_active_weekday",
]  # noqa: E501

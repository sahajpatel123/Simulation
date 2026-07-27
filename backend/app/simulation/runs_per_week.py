"""Pure helpers for the per-user runs-per-week endpoint.

Composes a small "activity over time" payload: the
number of sims the user ran in each of the last 4 weeks
(current + previous 3), suitable for a 4-bar chart on
the dashboard.

The helper is pure-Python. The route layer builds a
list of (week_start, sim_count) tuples and hands them
to :func:`build_runs_per_week`.

Output shape
------------
::

    {
      "weeks": list[
        {"week_start": "YYYY-MM-DD", "sim_count": int}
      ],
      "total_simulations": int,
      "average_per_week": float,
      "trend": "UP" | "DOWN" | "STEADY" | "INSUFFICIENT_DATA",
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


def build_runs_per_week(
    week_buckets: list[tuple] | None = None,
) -> dict:
    """Compose the per-user runs-per-week digest.

    Args:
        week_buckets: list of ``(week_start, sim_count)``
            tuples ordered from oldest to newest. week_start
            is a datetime or ISO date string.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    weeks: list[dict] = []
    for entry in week_buckets or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        ws = entry[0]
        count = _safe_int(entry[1])
        if hasattr(ws, "isoformat"):
            ws_str = ws.isoformat()[:10]  # YYYY-MM-DD
        elif isinstance(ws, str):
            ws_str = ws[:10]
        else:
            continue
        weeks.append({
            "week_start": ws_str,
            "sim_count": count,
        })

    total_simulations = sum(w["sim_count"] for w in weeks)
    average_per_week = (
        round(total_simulations / len(weeks), 1)
        if weeks
        else 0.0
    )

    # Compute trend: compare latest week to earliest
    # week.
    if len(weeks) < 2:
        trend = "INSUFFICIENT_DATA"
    else:
        latest = weeks[-1]["sim_count"]
        earliest = weeks[0]["sim_count"]
        if latest > earliest:
            trend = "UP"
        elif latest < earliest:
            trend = "DOWN"
        else:
            trend = "STEADY"

    severity = (
        SIGNAL_OK
        if trend == "UP"
        else SIGNAL_CRITICAL
        if trend == "DOWN"
        else SIGNAL_WATCH
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "trend",
        "value": trend,
        "severity": severity,
        "display": f"Run trend: {trend.lower()}",
    })

    # ---- Narrative ------------------------------------------------
    if not weeks:
        narrative = (
            "Not enough sim activity to chart the trend - "
            "run a few sims to populate this tile."
        )
    else:
        weekly_summary = ", ".join(
            f"{w['week_start'][-5:]} {w['sim_count']} sim(s)"
            for w in weeks
        )
        narrative = (
            f"{total_simulations} total sim(s) across "
            f"{len(weeks)} week(s), {average_per_week} avg/week "
            f"({trend.lower()}). {weekly_summary}."
        )

    return {
        "weeks": weeks,
        "total_simulations": total_simulations,
        "average_per_week": average_per_week,
        "trend": trend,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_runs_per_week",
]  # noqa: E501

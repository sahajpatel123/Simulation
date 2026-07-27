"""Pure helpers for the per-user usage-by-week endpoint.

Composes weekly volume counts (sims, decisions, outcomes)
for the last N weeks so the dashboard's 'usage over
time' chart can render without re-querying the DB for
each week.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the rolling-N-week rows and hands the list
to :func:`build_usage_by_week`.

Output shape
------------
::

    {
      "week_count": int,
      "weeks": [
        {
          "week_start": "YYYY-MM-DD",
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

MAX_WEEKS: int = 12

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


def build_usage_by_week(
    week_buckets: list[dict] | None = None,
) -> dict:
    """Compose the per-user usage-by-week digest.

    Args:
        week_buckets: list of week dicts from the route
            layer. Each must expose ``week_start``
            (ISO date string or datetime),
            ``sim_count``, ``decision_count``,
            ``outcome_count``.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    weeks: list[dict] = []
    for raw in week_buckets or []:
        if not isinstance(raw, dict):
            continue
        ws = raw.get("week_start")
        weeks.append({
            "week_start": (
                ws.isoformat() if hasattr(ws, "isoformat") else str(ws)
            ),
            "sim_count": _safe_int(raw.get("sim_count")),
            "decision_count": _safe_int(raw.get("decision_count")),
            "outcome_count": _safe_int(raw.get("outcome_count")),
        })

    weeks = weeks[:MAX_WEEKS]
    week_count = len(weeks)
    sim_total = sum(w["sim_count"] for w in weeks)
    dec_total = sum(w["decision_count"] for w in weeks)
    out_total = sum(w["outcome_count"] for w in weeks)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "week_count",
        "value": week_count,
        "severity": (
            SIGNAL_WATCH if week_count == 0 else SIGNAL_OK
        ),
        "display": f"{week_count} week(s) tracked",
    })
    if sim_total > 0:
        last = weeks[-1]
        prev = weeks[-2] if len(weeks) >= 2 else None
        if prev is not None:
            delta = last["sim_count"] - prev["sim_count"]
            key_signals.append({
                "label": "weekly_sim_delta",
                "value": delta,
                "severity": (
                    SIGNAL_OK if delta >= 0 else SIGNAL_WATCH
                ),
                "display": (
                    f"{'+' if delta >= 0 else ''}{delta} sim(s) "
                    f"this week vs prior"
                ),
            })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"{week_count} week(s) tracked; "
        f"{sim_total} sim(s), {dec_total} decision(s), "
        f"{out_total} outcome(s) total."
    )
    if weeks:
        most_recent = weeks[-1]
        sentences.append(
            f"Latest week ({most_recent['week_start']}): "
            f"{most_recent['sim_count']} sim(s), "
            f"{most_recent['decision_count']} decision(s), "
            f"{most_recent['outcome_count']} outcome(s)."
        )
    narrative = " ".join(sentences)

    return {
        "week_count": week_count,
        "sim_total": sim_total,
        "decision_total": dec_total,
        "outcome_total": out_total,
        "weeks": weeks,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_WEEKS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_usage_by_week",
]  # noqa: E501

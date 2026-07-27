"""Pure helpers for the per-user quick-stats endpoint.

Composes a minimal "one-liner" account summary for
mobile widgets + sidebars. Different from
/me/dashboard (which is verbose) — this is intentionally
small so it can be embedded in a tight UI surface.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls each count and hands them to
:func:`build_quick_stats`.

Output shape
------------
::

    {
      "total_projects": int,
      "total_simulations": int,
      "total_decisions": int,
      "total_outcomes": int,
      "account_age_days": int,
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


def build_quick_stats(
    total_projects: int = 0,
    total_simulations: int = 0,
    total_decisions: int = 0,
    total_outcomes: int = 0,
    account_age_days: int = 0,
) -> dict:
    """Compose the per-user quick-stats digest.

    Args:
        total_projects: count of projects owned.
        total_simulations: count of simulation rows.
        total_decisions: count of decision rows.
        total_outcomes: count of outcome rows.
        account_age_days: days since signup.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    total_projects = _safe_int(total_projects)
    total_simulations = _safe_int(total_simulations)
    total_decisions = _safe_int(total_decisions)
    total_outcomes = _safe_int(total_outcomes)
    account_age_days = _safe_int(account_age_days)
    total_activity = (
        total_simulations
        + total_decisions
        + total_outcomes
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "total_projects",
        "value": total_projects,
        "severity": (
            SIGNAL_WATCH if total_projects == 0 else SIGNAL_OK
        ),
        "display": f"{total_projects} project(s)",
    })
    if account_age_days > 0:
        key_signals.append({
            "label": "account_age_days",
            "value": account_age_days,
            "severity": (
                SIGNAL_OK if account_age_days >= 30
                else SIGNAL_WATCH
            ),
            "display": f"Account {account_age_days}d old",
        })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"{total_projects} project(s); "
        f"{total_activity} action(s) total."
    )
    if account_age_days > 0:
        if account_age_days < 7:
            age_label = "less than a week"
        elif account_age_days < 30:
            age_label = "less than a month"
        elif account_age_days < 90:
            age_label = "less than a quarter"
        elif account_age_days < 365:
            age_label = "less than a year"
        else:
            age_label = "well established"
        sentences.append(f"Account is {age_label}.")
    narrative = " ".join(sentences)

    return {
        "total_projects": total_projects,
        "total_simulations": total_simulations,
        "total_decisions": total_decisions,
        "total_outcomes": total_outcomes,
        "account_age_days": account_age_days,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "build_quick_stats",
]  # noqa: E501

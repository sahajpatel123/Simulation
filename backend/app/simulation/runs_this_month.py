"""Pure helpers for the per-user runs-this-month endpoint.

Composes a tiny integer payload for the dashboard's
tier-quota widget: how many sims the user has run this
calendar month, vs their tier's monthly cap.

The helper is pure-Python. The route layer pulls the
count + tier_cap and hands them to
:func:`build_runs_this_month`.

Output shape
------------
::

    {
      "runs_this_month": int,
      "monthly_cap": int,
      "remaining": int,
      "tier": str,
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


def _format_severity(used: int, cap: int) -> str:
    if cap <= 0:
        return SIGNAL_WATCH
    if used >= cap:
        return SIGNAL_CRITICAL
    if used / cap >= 0.8:
        return SIGNAL_WATCH
    return SIGNAL_OK


def build_runs_this_month(
    runs_this_month: int = 0,
    monthly_cap: int = 0,
    tier: str = "FREE",
    now: object | None = None,
) -> dict:
    """Compose the per-user runs-this-month digest.

    Args:
        runs_this_month: count of sims created since the
            first day of the current calendar month.
        monthly_cap: tier's monthly cap (from
            ``TIER_LIMITS``).
        tier: tier label (``FREE`` / ``PRO`` / ...).
        now: optional reference time (kept for shape
            symmetry with other digests - currently
            unused).

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    used = _safe_int(runs_this_month)
    cap = _safe_int(monthly_cap)
    remaining = max(0, cap - used)
    severity = _format_severity(used, cap)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "runs_this_month",
        "value": used,
        "severity": severity,
        "display": (
            f"{used}/{cap} sim(s) this month"
            if cap > 0
            else f"{used} sim(s) this month"
        ),
    })

    # ---- Narrative ------------------------------------------------
    if cap <= 0:
        narrative = (
            f"{used} sim(s) run this month "
            f"(no monthly cap)."
        )
    elif used >= cap:
        narrative = (
            f"Monthly sim quota exhausted "
            f"({used}/{cap}). Upgrade or wait for the "
            f"next cycle."
        )
    elif used / cap >= 0.8:
        narrative = (
            f"Approaching monthly sim quota "
            f"({used}/{cap})."
        )
    else:
        narrative = (
            f"{used}/{cap} sim(s) run this month "
            f"({remaining} remaining)."
        )

    return {
        "runs_this_month": used,
        "monthly_cap": cap,
        "remaining": remaining,
        "tier": tier or "FREE",
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_runs_this_month",
]  # noqa: E501

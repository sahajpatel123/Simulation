"""Pure helpers for the per-user sim-failure-rate endpoint.

Composes a single "what % of your sims failed?" payload
so the dashboard can show a system-reliability widget.

The helper is pure-Python. The route layer passes
the total + failed sim counts to
:func:`build_sim_failure_rate`.

Output shape
------------
::

    {
      "total_simulations": int,
      "failed_simulations": int,
      "failure_rate_pct": float,
      "verdict": "RELIABLE" | "ACCEPTABLE" | "UNRELIABLE" | "INSUFFICIENT_DATA",
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Failure-rate thresholds (% of failed sims).
RELIABLE_MAX: float = 5.0
ACCEPTABLE_MAX: float = 15.0

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


def build_sim_failure_rate(
    total_simulations: int = 0,
    failed_simulations: int = 0,
) -> dict:
    """Compose the per-user sim-failure-rate digest.

    Args:
        total_simulations: total sims across the user's
            projects.
        failed_simulations: sims whose status is
            'FAILED' across the user's projects.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    total_simulations = _safe_int(total_simulations)
    failed_simulations = min(
        _safe_int(failed_simulations), total_simulations,
    )

    failure_rate_pct = 0.0
    if total_simulations > 0:
        failure_rate_pct = round(
            failed_simulations / total_simulations * 100.0,
            1,
        )

    if total_simulations == 0:
        verdict = "INSUFFICIENT_DATA"
    elif failure_rate_pct <= RELIABLE_MAX:
        verdict = "RELIABLE"
    elif failure_rate_pct <= ACCEPTABLE_MAX:
        verdict = "ACCEPTABLE"
    else:
        verdict = "UNRELIABLE"

    severity = (
        SIGNAL_OK
        if verdict == "RELIABLE"
        else SIGNAL_WATCH
        if verdict == "ACCEPTABLE"
        else SIGNAL_CRITICAL
    )

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    if verdict != "INSUFFICIENT_DATA":
        key_signals.append({
            "label": "failure_rate_pct",
            "value": failure_rate_pct,
            "severity": severity,
            "display": (
                f"Sim failure rate: {failure_rate_pct:.1f}%"
            ),
        })

    # ---- Narrative ------------------------------------------------
    if verdict == "INSUFFICIENT_DATA":
        narrative = (
            "No simulations yet - run a few to populate "
            "this tile."
        )
    else:
        narrative = (
            f"Sim failure rate is {failure_rate_pct:.1f}% "
            f"({failed_simulations} failed of "
            f"{total_simulations} total) - {verdict.lower()}."
        )

    return {
        "total_simulations": total_simulations,
        "failed_simulations": failed_simulations,
        "failure_rate_pct": failure_rate_pct,
        "verdict": verdict,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "RELIABLE_MAX",
    "ACCEPTABLE_MAX",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_sim_failure_rate",
]  # noqa: E501

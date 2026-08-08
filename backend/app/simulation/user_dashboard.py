"""Pure helpers for the user dashboard endpoint.

Composes a single-payload snapshot of the user's account
state so the "Account" page can render one paragraph +
key tiles without fanning out to /me/blindspots + the
project list + the simulation accuracy profile.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls the rows and hands them to
:func:`build_user_dashboard`.

What it answers
--------------
* "How much of my monthly simulation quota have I used?"
* "How many projects / sims / decisions / outcomes
  do I have?"
* "Is my calibration improving over time?"
* "How many recent blindspots have been flagged?"
* "When did I last touch anything?"

Output shape
------------
::

    {
      "account_age_days": int,
      "tier": str,
      "monthly_usage": {"used": int, "cap": int, "remaining": int},
      "project_count": int,
      "simulation_count": int,
      "decision_count": int,
      "outcome_count": int,
      "last_activity_at": str | None,
      "calibration_health": dict | None,
      "blindspot_count": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

from datetime import UTC

# Cap on monthly sim runs for the FREE tier. Higher
# tiers are enforced elsewhere; this is the dashboard's
# baseline reference.
FREE_TIER_MONTHLY_CAP: int = 2

# Maximum days of the account-age band shown in the
# dashboard narrative ("<30 days old", etc.).
ACCOUNT_AGE_BANDS: tuple[tuple[int, str], ...] = (
    (7, "less than a week old"),
    (30, "less than a month old"),
    (90, "less than a quarter old"),
    (365, "less than a year old"),
    (10_000, "well established"),
)

# Signal severity buckets — keep aligned with the other
# dashboard tiles.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Thresholds for monthly-quota severity. Approaching the
# cap → watch. At-or-over cap → critical.
QUOTA_WARN_RATIO: float = 0.8


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int,)):
        return int(value)
    return default


def _format_account_age(days: int) -> str:
    # ``<=`` so an account that's exactly 7/30/90/365 days
    # old falls into the corresponding band rather than
    # skipping past it (e.g. day-90 → "less than a quarter
    # old" not "less than a year old").
    for limit, label in ACCOUNT_AGE_BANDS:
        if days <= limit:
            return label
    return "well established"


def _format_quota_severity(used: int, cap: int) -> str:
    if cap <= 0:
        return SIGNAL_WATCH
    if used >= cap:
        return SIGNAL_CRITICAL
    if used / cap >= QUOTA_WARN_RATIO:
        return SIGNAL_WATCH
    return SIGNAL_OK


def build_user_dashboard(
    account_created_at: object | None,
    tier: str,
    monthly_sim_used: int,
    monthly_sim_cap: int | None = None,
    project_count: int = 0,
    simulation_count: int = 0,
    decision_count: int = 0,
    outcome_count: int = 0,
    last_activity_at: object | None = None,
    calibration_health: dict | None = None,
    blindspot_count: int = 0,
    now: object | None = None,
) -> dict:
    """Compose the user dashboard snapshot.

    Args:
        account_created_at: signup timestamp (datetime or
            ISO string).
        tier: subscription tier label ("FREE" / "PRO" /
            etc.).
        monthly_sim_used: simulations run this calendar
            month.
        monthly_sim_cap: tier's monthly cap. Defaults to
            :data:`FREE_TIER_MONTHLY_CAP` when None.
        project_count: total projects owned by user.
        simulation_count: total simulations run.
        decision_count: total decisions enqueued.
        outcome_count: total outcomes recorded.
        last_activity_at: most-recent event timestamp
            (any of: project create, sim enqueue,
            decision enqueue, outcome submit).
        calibration_health: pass-through output of
            :func:`build_calibration_health` (optional).
        blindspot_count: count of blindspots flagged in
            the recent window.
        now: optional override for the current time (for
            testability). When provided, used to compute
            account age and "days since last activity".

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    from datetime import datetime

    used = _safe_int(monthly_sim_used)
    cap = (
        _safe_int(monthly_sim_cap)
        if monthly_sim_cap is not None
        else FREE_TIER_MONTHLY_CAP
    )
    quota_severity = _format_quota_severity(used, cap)

    # ---- Account age -------------------------------------------------
    account_age_days: int | None = None
    account_age_label: str | None = None
    if account_created_at is not None:
        ts = account_created_at
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except Exception:
                ts = None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            ref = now if isinstance(now, datetime) else (
                datetime.now(UTC)
            )
            if isinstance(ref, str):
                try:
                    ref = datetime.fromisoformat(ref)
                except Exception:
                    ref = datetime.now(UTC)
            if isinstance(ref, datetime) and ref.tzinfo is None:
                ref = ref.replace(tzinfo=UTC)
            try:
                delta = ref - ts
                account_age_days = max(0, delta.days)
                account_age_label = _format_account_age(
                    account_age_days,
                )
            except Exception:
                pass
    if account_age_days is None:
        # Fallback when the timestamp couldn't be parsed.
        account_age_days = 0
        account_age_label = "fresh"

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "tier",
        "value": tier or "FREE",
        "severity": SIGNAL_OK,
        "display": f"Tier: {tier or 'FREE'}",
    })
    key_signals.append({
        "label": "monthly_sims",
        "value": used,
        "severity": quota_severity,
        "display": (
            f"{used}/{cap} simulations this month"
            if cap > 0 else f"{used} simulations this month"
        ),
    })
    key_signals.append({
        "label": "project_count",
        "value": project_count,
        "severity": SIGNAL_OK,
        "display": f"{project_count} project(s)",
    })
    if blindspot_count > 0:
        key_signals.append({
            "label": "blindspot_count",
            "value": blindspot_count,
            "severity": (
                SIGNAL_CRITICAL
                if blindspot_count >= 3 else SIGNAL_WATCH
            ),
            "display": f"{blindspot_count} blindspot(s) flagged",
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"Account is {account_age_label} and on the "
        f"{tier or 'FREE'} tier."
    )
    sentences.append(
        f"{project_count} project(s), {simulation_count} "
        f"simulation(s), {decision_count} decision(s), "
        f"{outcome_count} outcome(s) recorded."
    )
    if cap > 0 and used >= cap:
        sentences.append(
            "Monthly simulation quota is exhausted — upgrade "
            "or wait for the next cycle."
        )
    elif cap > 0 and used / cap >= QUOTA_WARN_RATIO:
        sentences.append(
            "Approaching the monthly simulation quota."
        )
    if blindspot_count:
        sentences.append(
            f"{blindspot_count} blindspot(s) flagged in the "
            f"recent window."
        )
    last_iso = _iso(last_activity_at)
    if last_iso:
        sentences.append(f"Last activity: {last_iso}.")
    narrative = " ".join(sentences)

    return {
        "account_age_days": account_age_days,
        "tier": tier or "FREE",
        "monthly_usage": {
            "used": used,
            "cap": cap,
            "remaining": max(0, cap - used),
        },
        "project_count": project_count,
        "simulation_count": simulation_count,
        "decision_count": decision_count,
        "outcome_count": outcome_count,
        "last_activity_at": last_iso,
        "calibration_health": calibration_health,
        "blindspot_count": blindspot_count,
        "account_age_label": account_age_label,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "FREE_TIER_MONTHLY_CAP",
    "ACCOUNT_AGE_BANDS",
    "QUOTA_WARN_RATIO",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_user_dashboard",
]  # noqa: E501

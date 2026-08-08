"""Pure helpers for the per-project stale-check endpoint.

Inverse of activity-feed: where activity-feed shows
what just happened, stale-check surfaces what is OUT OF
DATE. Founders often don't realise their assumptions
are stale and the predictions are now unreliable.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls each source's latest timestamp and hands
them to :func:`build_stale_check`.

Standard staleness thresholds (in days)
--------------------------------------
* assumptions      - 30 days since the most recent extraction
* sims             - 14 days since the most recent completed sim
* outcomes         - 30 days since the most recent outcome
* decisions        - 14 days since the most recent completed decision
* premortem        - 60 days since the most recent premortem
* interventions    - 30 days since the most recent intervention
"""
from __future__ import annotations

from datetime import UTC, datetime

# Per-source staleness thresholds (days).
# Wider thresholds for sources that change less often.
ASSUMPTIONS_STALE_DAYS: int = 30
SIM_STALE_DAYS: int = 14
OUTCOMES_STALE_DAYS: int = 30
DECISIONS_STALE_DAYS: int = 14
PREMORTEM_STALE_DAYS: int = 60
INTERVENTIONS_STALE_DAYS: int = 30

# Signal severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Critical threshold multiplier. A source that is >=
# 2x the standard threshold is "very stale" -> critical.
CRITICAL_MULTIPLIER: float = 2.0


def _diff_days(latest: datetime | None, now: datetime) -> int | None:
    """Days between ``latest`` and ``now``. ``None`` when
    ``latest`` is missing so callers can distinguish
    'never' from 'old'."""
    if latest is None:
        return None
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)
    delta = now - latest
    return max(0, delta.days)


def _classify_severity(days: int | None, threshold: int) -> str:
    """Severity bucket for a single source."""
    if days is None:
        # Never updated - the staleness is unbounded
        # (cannot regress). Treat as critical so the
        # founder definitely re-runs analysis.
        return SIGNAL_CRITICAL
    if days >= int(threshold * CRITICAL_MULTIPLIER):
        return SIGNAL_CRITICAL
    if days >= threshold:
        return SIGNAL_WATCH
    return SIGNAL_OK


def _rec_text(
    source_label: str,
    days: int | None,
    threshold: int,
) -> str:
    if days is None:
        return (
            f"No {source_label.lower()} on record yet — re-run "
            f"the analysis."
        )
    if days >= int(threshold * CRITICAL_MULTIPLIER):
        return (
            f"{source_label} is {days}d old (threshold "
            f"{threshold}d) — strongly consider regenerating."
        )
    return (
        f"{source_label} is {days}d old (threshold "
        f"{threshold}d) — consider refreshing."
    )


def build_stale_check(
    latest_assumption_at: datetime | None,
    latest_sim_completed_at: datetime | None,
    latest_outcome_at: datetime | None,
    latest_decision_completed_at: datetime | None,
    latest_premortem_at: datetime | None,
    latest_intervention_at: datetime | None,
    now: datetime | None = None,
) -> dict:
    """Compose the per-project stale-check digest.

    Args:
        latest_*_at: most-recent timestamp for each source
            (datetime or None when absent).
        now: optional reference time for testability.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    ref = now if isinstance(now, datetime) else (
        datetime.now(UTC)
    )

    sources = [
        {
            "name": "assumptions",
            "latest_at": latest_assumption_at,
            "threshold": ASSUMPTIONS_STALE_DAYS,
        },
        {
            "name": "sims",
            "latest_at": latest_sim_completed_at,
            "threshold": SIM_STALE_DAYS,
        },
        {
            "name": "outcomes",
            "latest_at": latest_outcome_at,
            "threshold": OUTCOMES_STALE_DAYS,
        },
        {
            "name": "decisions",
            "latest_at": latest_decision_completed_at,
            "threshold": DECISIONS_STALE_DAYS,
        },
        {
            "name": "premortem",
            "latest_at": latest_premortem_at,
            "threshold": PREMORTEM_STALE_DAYS,
        },
        {
            "name": "interventions",
            "latest_at": latest_intervention_at,
            "threshold": INTERVENTIONS_STALE_DAYS,
        },
    ]

    enriched = []
    stale_count = 0
    for src in sources:
        days = _diff_days(src["latest_at"], ref)
        severity = _classify_severity(
            days, src["threshold"],
        )
        if severity != SIGNAL_OK:
            stale_count += 1
        enriched.append({
            "name": src["name"],
            "threshold_days": src["threshold"],
            "days_since": days,
            "severity": severity,
            "recommendation": _rec_text(
                src["name"], days, src["threshold"],
            ),
        })

    sources_checked = len(sources)

    # ---- Key signals ----------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "stale_source_count",
        "value": stale_count,
        "severity": (
            SIGNAL_CRITICAL
            if stale_count >= 3
            else SIGNAL_WATCH if stale_count >= 1 else SIGNAL_OK
        ),
        "display": (
            f"{stale_count} of {sources_checked} source(s) "
            f"stale"
        ),
    })

    # ---- Narrative ------------------------------------------------
    sentences: list[str] = []
    if stale_count == 0:
        sentences.append(
            f"All {sources_checked} data sources are fresh."
        )
    else:
        sentences.append(
            f"{stale_count} of {sources_checked} data sources "
            f"are out of date."
        )
        critical_sources = [
            s["name"]
            for s in enriched
            if s["severity"] == SIGNAL_CRITICAL
        ]
        if critical_sources:
            sentences.append(
                f"Critical: {', '.join(critical_sources)}."
            )
    narrative = " ".join(sentences)

    return {
        "stale_count": stale_count,
        "sources_checked": sources_checked,
        "sources": enriched,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "ASSUMPTIONS_STALE_DAYS",
    "SIM_STALE_DAYS",
    "OUTCOMES_STALE_DAYS",
    "DECISIONS_STALE_DAYS",
    "PREMORTEM_STALE_DAYS",
    "INTERVENTIONS_STALE_DAYS",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_stale_check",
]  # noqa: E501

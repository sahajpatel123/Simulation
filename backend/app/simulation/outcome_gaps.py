"""Pure helpers for the per-project outcome-feedback gaps digest.

A completed simulation only teaches the calibration layer once a founder
records real-world feedback against it in ``founder_outcomes``. This
module turns "how many of my runs are unscored?" into an actionable,
oldest-first list: which simulations still need feedback, how stale they
are, whether the run would actually carry learning weight, and a plain
language recommendation for the founder.

Everything here is pure (no DB, no I/O); the route layer owns the SQL
queries and hands plain row dicts to :func:`build_outcome_gaps_digest`.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

from app.simulation.founder_outcomes_export import (
    predicted_conversion_from_results,
)

# A run is "learning-eligible" when its signal quality reaches this floor.
# Below it the calibration engine assigns zero learning weight even if the
# founder submits an outcome — mirrors ``submit_outcome_feedback``.
LEARNING_ELIGIBLE_SIGNAL_QUALITY: float = 0.25

# Age thresholds (days) for the urgency tiers. A month-old learning-eligible
# run is the highest-priority gap: the model is being calibrated against
# increasingly stale reality. A week is the "worth doing soon" line.
STALE_DAYS: int = 30
RECENT_DAYS: int = 7

URGENCY_HIGH: str = "HIGH"
URGENCY_MEDIUM: str = "MEDIUM"
URGENCY_LOW: str = "LOW"


def _utcnow() -> datetime:
    """Current UTC timestamp, injectable through ``now`` for tests."""
    return datetime.now(UTC)


def _safe_float(value: Any) -> float | None:
    """Coerce a value to a finite float or ``None`` (never NaN/inf)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> int | None:
    """Coerce a value to a positive int or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _safe_str(value: Any, max_length: int = 120) -> str | None:
    """Coerce a value to a trimmed, length-capped string or ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _safe_datetime(value: Any) -> datetime | None:
    """Coerce a datetime (or ISO string) to a tz-aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_results(value: Any) -> dict[str, Any]:
    """Normalise a JSONB blob (dict, string, or ``None``) into a dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def age_days(created_at: datetime | None, now: datetime | None = None) -> int:
    """Whole days between ``created_at`` and ``now`` (0 when missing)."""
    reference = now or _utcnow()
    created = _safe_datetime(created_at)
    if created is None:
        return 0
    delta = reference - created
    return max(0, int(delta.total_seconds() // 86400))


def learning_eligible(signal_quality: float | None) -> bool:
    """Whether a run would carry calibration learning weight if scored."""
    return (
        signal_quality is not None
        and signal_quality >= LEARNING_ELIGIBLE_SIGNAL_QUALITY
    )


def _urgency(signal_quality: float | None, age: int) -> str:
    """Prioritise stale, learning-eligible runs over fresh low-signal ones."""
    eligible = learning_eligible(signal_quality)
    if eligible and age >= STALE_DAYS:
        return URGENCY_HIGH
    if eligible or age >= RECENT_DAYS:
        return URGENCY_MEDIUM
    return URGENCY_LOW


def _recommendation(
    urgency: str,
    *,
    learning_eligible: bool,
    has_results: bool,
    age: int,
) -> str:
    """Plain-language next step for one unscored run."""
    if urgency == URGENCY_HIGH:
        return (
            f"This learning-eligible run is {age} days old — record the "
            "real-world outcome now so calibration is not trained on stale data."
        )
    if urgency == URGENCY_MEDIUM:
        if learning_eligible:
            return (
                "This run carries calibration value — scoring it will "
                "meaningfully improve future predictions."
            )
        return (
            f"This run is {age} days old — score it to keep your outcome "
            "history complete, even though its signal is below the "
            "learning-weight floor."
        )
    if not has_results:
        return (
            "This run has no stored result payload, so scoring it would not "
            "add a prediction-vs-actual pair; deprioritise it."
        )
    return (
        "Recent and below the learning-weight floor — optional to score; "
        "prioritise HIGH and MEDIUM runs first."
    )


def build_outcome_gap_item(
    row: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one digest item from a raw simulation row dict."""
    simulation_id = _safe_int(row.get("simulation_id"))
    created_at = _safe_datetime(row.get("created_at"))
    signal_quality = _safe_float(row.get("signal_quality"))
    results = _coerce_results(row.get("results_json"))
    age = age_days(created_at, now)
    eligible = learning_eligible(signal_quality)
    urgency = _urgency(signal_quality, age)

    return {
        "simulation_id": simulation_id or 0,
        "created_at": created_at or now or _utcnow(),
        "age_days": age,
        "signal_quality": signal_quality,
        "predicted_conversion_rate": predicted_conversion_from_results(
            results
        ),
        "product_type_detected": _safe_str(results.get("product_type_detected")),
        "primary_failure_domain": _safe_str(
            results.get("primary_failure_domain")
        ),
        "has_results": bool(results),
        "learning_eligible": eligible,
        "urgency": urgency,
        "recommendation": _recommendation(
            urgency,
            learning_eligible=eligible,
            has_results=bool(results),
            age=age,
        ),
    }


def _narrative(
    *,
    total_completed: int,
    scored: int,
    unscored: int,
    coverage_rate_pct: float,
    learning_eligible_unscored: int,
    learning_eligible_only: bool,
) -> str:
    """Human-readable summary of the outcome-feedback gap."""
    if total_completed == 0:
        return (
            "No completed simulations yet — run one to get a prediction "
            "you can validate in the real world."
        )
    if unscored == 0:
        return (
            "All completed simulations have recorded outcome feedback — "
            "the calibration layer already has everything it can use "
            "from this project."
        )

    prefix = (
        "Showing learning-eligible unscored runs only. "
        if learning_eligible_only
        else ""
    )
    base = (
        f"Only {scored} of {total_completed} completed runs have outcome "
        f"feedback ({coverage_rate_pct:.1f}%). Scoring the {unscored} "
        "unscored run(s) below teaches the calibration layer how this "
        "project's predictions hold up in the real world."
    )
    if learning_eligible_unscored > 0 and not learning_eligible_only:
        base += (
            f" {learning_eligible_unscored} of those runs have signal "
            "quality ≥ 0.25 and would feed calibration if the product "
            "hasn't changed since the run."
        )
    return prefix + base


def build_outcome_gaps_summary(
    *,
    total_completed: int,
    scored: int,
    unscored: int,
    learning_eligible_unscored: int,
    oldest_unscored_created_at: Any,
    learning_eligible_only: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Roll up the project-level gap counts into a summary dict."""
    coverage_rate_pct = (
        round((scored / total_completed) * 100.0, 2)
        if total_completed > 0
        else 0.0
    )
    oldest_age = age_days(
        _safe_datetime(oldest_unscored_created_at),
        now,
    )
    return {
        "total_completed": max(0, int(total_completed or 0)),
        "scored": max(0, int(scored or 0)),
        "unscored": max(0, int(unscored or 0)),
        "coverage_rate_pct": coverage_rate_pct,
        "learning_eligible_unscored": max(
            0, int(learning_eligible_unscored or 0)
        ),
        "oldest_unscored_age_days": (
            oldest_age if oldest_unscored_created_at is not None else None
        ),
        "narrative": _narrative(
            total_completed=max(0, int(total_completed or 0)),
            scored=max(0, int(scored or 0)),
            unscored=max(0, int(unscored or 0)),
            coverage_rate_pct=coverage_rate_pct,
            learning_eligible_unscored=max(
                0, int(learning_eligible_unscored or 0)
            ),
            learning_eligible_only=learning_eligible_only,
        ),
    }


def build_outcome_gaps_digest(
    *,
    project_id: int,
    rows: list[dict[str, Any]],
    total_completed: int,
    scored_count: int,
    unscored_total: int,
    learning_eligible_unscored: int,
    oldest_unscored_created_at: Any,
    limit: int,
    learning_eligible_only: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose the full outcome-feedback gaps digest payload.

    ``rows`` are the raw simulation row dicts for the current page
    (oldest first, from the route layer). Summary counts are exact across
    the whole filtered universe even when pagination truncates ``rows``.
    """
    reference = now or _utcnow()
    items = [
        build_outcome_gap_item(dict(row), now=reference)
        for row in rows
    ]
    summary = build_outcome_gaps_summary(
        total_completed=total_completed,
        scored=scored_count,
        unscored=unscored_total,
        learning_eligible_unscored=learning_eligible_unscored,
        oldest_unscored_created_at=oldest_unscored_created_at,
        learning_eligible_only=learning_eligible_only,
        now=reference,
    )
    return {
        "project_id": int(project_id),
        "generated_at": reference,
        "summary": summary,
        "items": items,
        "limit": int(limit),
        "has_more": unscored_total > len(items),
    }


__all__ = [
    "LEARNING_ELIGIBLE_SIGNAL_QUALITY",
    "RECENT_DAYS",
    "STALE_DAYS",
    "URGENCY_HIGH",
    "URGENCY_LOW",
    "URGENCY_MEDIUM",
    "age_days",
    "build_outcome_gap_item",
    "build_outcome_gaps_digest",
    "build_outcome_gaps_summary",
    "learning_eligible",
]

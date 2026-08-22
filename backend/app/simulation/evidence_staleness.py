"""Evidence-staleness analysis for a project's validation history.

The evidence digest answers *how much* risk has been validated and the
momentum forecast answers *how fast*. This module answers a question both
leave open: *how old is the evidence, and what has quietly gone untested?*

Every non-hidden assumption gets one freshness verdict based on the age of
its most recent logged experiment:

* ``FRESH``       — latest evidence within ``fresh_days`` (default 14);
* ``AGING``       — latest evidence within ``aging_days`` (default 45);
* ``STALE``       — latest evidence older than ``aging_days``;
* ``NEVER_TESTED`` — no evidence logged at all;
* ``UNKNOWN``     — evidence exists but no parseable timestamp.

``STALE`` and ``NEVER_TESTED`` assumptions are *actionable*: together they
form the founder's re-test queue, prioritised by sensitivity and returned
with concrete recommendations.

Pure module (no DB, no I/O): the route passes already-loaded assumption and
evidence rows plus an optional ``now``, so every value is deterministic and
easily testable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.simulation.validation_momentum import _coerce_timestamp

STALENESS_MODEL: str = "evidence_staleness_v1"

# Default freshness windows (calendar days since the latest experiment).
DEFAULT_FRESH_DAYS: int = 14
DEFAULT_AGING_DAYS: int = 45

# Hard bounds for caller-supplied windows (validated again at the schema
# layer; this guard keeps direct builder calls sane too).
MIN_WINDOW_DAYS: int = 1
MAX_WINDOW_DAYS: int = 365

FRESHNESS_FRESH: str = "FRESH"
FRESHNESS_AGING: str = "AGING"
FRESHNESS_STALE: str = "STALE"
FRESHNESS_NEVER_TESTED: str = "NEVER_TESTED"
FRESHNESS_UNKNOWN: str = "UNKNOWN"

# Lower sorts first: the re-test queue leads with what was never tested,
# then what went stale longest ago.
_FRESHNESS_RANK: dict[str, int] = {
    FRESHNESS_NEVER_TESTED: 0,
    FRESHNESS_STALE: 1,
    FRESHNESS_AGING: 2,
    FRESHNESS_FRESH: 3,
    FRESHNESS_UNKNOWN: 4,
}

_MAX_RECOMMENDATIONS: int = 3


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _sensitivity_rank(sensitivity: str) -> int:
    """Higher ranks sort earlier (HIGH before MEDIUM before LOW)."""
    label = _safe_text(sensitivity).strip().upper()
    return {"HIGH": 3, "MEDIUM": 2}.get(label, 1)


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _validate_windows(fresh_days: int, aging_days: int) -> None:
    for name, value in (("fresh_days", fresh_days), ("aging_days", aging_days)):
        if not MIN_WINDOW_DAYS <= value <= MAX_WINDOW_DAYS:
            raise ValueError(
                f"{name} must be between {MIN_WINDOW_DAYS} and "
                f"{MAX_WINDOW_DAYS} days, got {value}"
            )
    if fresh_days >= aging_days:
        raise ValueError(
            f"fresh_days ({fresh_days}) must be strictly less than "
            f"aging_days ({aging_days})"
        )


def build_evidence_staleness(
    assumptions: list[Any],
    evidence: list[Any],
    *,
    project_id: int,
    now: datetime | None = None,
    fresh_days: int = DEFAULT_FRESH_DAYS,
    aging_days: int = DEFAULT_AGING_DAYS,
) -> dict[str, Any]:
    """Return the per-assumption freshness payload for one project.

    ``assumptions`` and ``evidence`` are pre-loaded ORM rows (or dicts);
    ``now`` defaults to the current UTC time and exists so callers — and
    tests — can pin every derived age deterministically.
    """
    _validate_windows(fresh_days, aging_days)
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    latest_by_assumption: dict[int, datetime] = {}
    count_by_assumption: dict[int, int] = {}
    for row in evidence or []:
        assumption_id = _safe_int(_row_value(row, "assumption_id"))
        if assumption_id <= 0:
            continue
        count_by_assumption[assumption_id] = (
            count_by_assumption.get(assumption_id, 0) + 1
        )
        created = _coerce_timestamp(_row_value(row, "created_at"))
        if created is not None:
            known = latest_by_assumption.get(assumption_id)
            if known is None or created > known:
                latest_by_assumption[assumption_id] = created

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        FRESHNESS_FRESH: 0,
        FRESHNESS_AGING: 0,
        FRESHNESS_STALE: 0,
        FRESHNESS_NEVER_TESTED: 0,
        FRESHNESS_UNKNOWN: 0,
    }
    oldest_days: float | None = None

    for assumption in assumptions or []:
        assumption_id = _safe_int(_row_value(assumption, "id"))
        evidence_count = count_by_assumption.get(assumption_id, 0)
        last_evidence_at = latest_by_assumption.get(assumption_id)
        days_since: float | None = None
        if last_evidence_at is not None:
            days_since = max(
                0.0, (reference - last_evidence_at).total_seconds() / 86400.0
            )
            oldest_days = (
                days_since if oldest_days is None else max(oldest_days, days_since)
            )

        if evidence_count == 0:
            freshness = FRESHNESS_NEVER_TESTED
        elif days_since is None:
            freshness = FRESHNESS_UNKNOWN
        elif days_since <= fresh_days:
            freshness = FRESHNESS_FRESH
        elif days_since <= aging_days:
            freshness = FRESHNESS_AGING
        else:
            freshness = FRESHNESS_STALE
        counts[freshness] += 1

        rows.append(
            {
                "assumption_id": assumption_id,
                "assumption_text": _safe_text(_row_value(assumption, "text")),
                "category": _row_value(assumption, "category"),
                "sensitivity": _safe_text(
                    _row_value(assumption, "sensitivity"), "MEDIUM"
                ),
                "evidence_count": evidence_count,
                "last_evidence_at": last_evidence_at.isoformat()
                if last_evidence_at is not None
                else None,
                "days_since_last_evidence": (
                    round(days_since, 2) if days_since is not None else None
                ),
                "freshness": freshness,
            }
        )

    rows.sort(
        key=lambda row: (
            _FRESHNESS_RANK.get(row["freshness"], 9),
            -_sensitivity_rank(row["sensitivity"]),
            row["evidence_count"],
            row["assumption_id"],
        )
    )

    total = len(rows)
    tested = sum(
        1 for row in rows if row["evidence_count"] > 0 and row["freshness"] != FRESHNESS_UNKNOWN
    )
    fresh = counts[FRESHNESS_FRESH]
    stale = counts[FRESHNESS_STALE]
    never_tested = counts[FRESHNESS_NEVER_TESTED]

    summary: dict[str, Any] = {
        "total_assumptions": total,
        "tested_assumptions": tested,
        "fresh_count": fresh,
        "aging_count": counts[FRESHNESS_AGING],
        "stale_count": stale,
        "never_tested_count": never_tested,
        "unknown_count": counts[FRESHNESS_UNKNOWN],
        "actionable_count": stale + never_tested,
        "fresh_share_of_tested_pct": (
            round(fresh / tested, 4) if tested > 0 else None
        ),
        "stale_share_pct": round(stale / total, 4) if total > 0 else None,
        "oldest_days_since_evidence": (
            round(oldest_days, 2) if oldest_days is not None else None
        ),
    }

    recommendations: list[str] = []
    for row in rows:
        if len(recommendations) >= _MAX_RECOMMENDATIONS:
            break
        if row["freshness"] == FRESHNESS_NEVER_TESTED:
            recommendations.append(
                f"Design a first experiment for "
                f"\"{row['assumption_text']}\" — it has never been tested."
            )
        elif row["freshness"] == FRESHNESS_STALE:
            recommendations.append(
                f"Re-test \"{row['assumption_text']}\" — latest evidence is "
                f"{row['days_since_last_evidence']:.0f} days old."
            )

    return {
        "project_id": _safe_int(project_id),
        "summary": summary,
        "rows": rows,
        "recommendations": recommendations,
        "meta": {
            "generated_at": reference.isoformat(),
            "model": STALENESS_MODEL,
            "fresh_days": fresh_days,
            "aging_days": aging_days,
        },
    }


__all__ = [
    "DEFAULT_AGING_DAYS",
    "DEFAULT_FRESH_DAYS",
    "FRESHNESS_AGING",
    "FRESHNESS_FRESH",
    "FRESHNESS_NEVER_TESTED",
    "FRESHNESS_STALE",
    "FRESHNESS_UNKNOWN",
    "MAX_WINDOW_DAYS",
    "MIN_WINDOW_DAYS",
    "STALENESS_MODEL",
    "build_evidence_staleness",
]

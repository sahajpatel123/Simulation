"""Pure builder for portfolio outcome-feedback coverage by product type.

The gap digests tell a founder *which runs* still need real-world feedback,
but a portfolio with mixed product lines still cannot answer "which category
of ideas has the weakest feedback loop?". This module rolls the same
outcome-feedback coverage up by the product type detected in each
simulation's results:

* Every completed simulation without a matching ``founder_outcomes`` row is
  an open gap; runs whose signal quality meets the calibration
  learning-weight floor are flagged learning-eligible, and stale
  learning-eligible runs are flagged high-priority.
* Each product type also reports the mean absolute gap between predicted and
  actual conversion on scored runs, so a founder can see both *where
  feedback is missing* and *where predictions are wrong*.
* Rows are sorted weakest-first (lowest coverage, then most unscored) so the
  least-calibrated product line appears first.

Everything here is pure Python (no SQL, no I/O); the route layer owns the
queries and hands plain row dicts to
:func:`build_product_type_outcome_gaps_digest`. Malformed rows are tolerated
and never raise.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.simulation.founder_outcomes_export import (
    predicted_conversion_from_results,
)
from app.simulation.outcome_gaps import (
    STALE_DAYS,
    URGENCY_HIGH,
    URGENCY_LOW,
    URGENCY_MEDIUM,
    _safe_datetime,
)

_UNKNOWN_PRODUCT_TYPE: str = "unknown"


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


def _safe_int(value: Any) -> int:
    """Coerce a value to a non-negative int (``0`` when unusable)."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)


def _safe_str(value: Any, max_length: int = 64) -> str:
    """Coerce a value to a trimmed, length-capped string."""
    if value is None:
        return _UNKNOWN_PRODUCT_TYPE
    text = str(value).strip()
    if not text:
        return _UNKNOWN_PRODUCT_TYPE
    return text[:max_length]


def _age_days(
    created_at: datetime | None,
    now: datetime | None = None,
) -> int | None:
    """Whole days between ``created_at`` and ``now`` (None when missing)."""
    reference = now or _utcnow()
    created = _safe_datetime(created_at)
    if created is None:
        return None
    delta = reference - created
    return max(0, int(delta.total_seconds() // 86400))


def _normalise_coverage_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce one raw coverage aggregate row into a safe dict."""
    if not isinstance(row, dict):
        return None
    product_type = _safe_str(row.get("product_type"))
    return {
        "product_type": product_type,
        "project_id": _safe_int(row.get("project_id")),
        "total_completed": _safe_int(row.get("total_completed")),
        "scored": _safe_int(row.get("scored")),
        "unscored": _safe_int(row.get("unscored")),
        "learning_eligible_unscored": _safe_int(
            row.get("learning_eligible_unscored")
        ),
        "high_priority_unscored": _safe_int(
            row.get("high_priority_unscored")
        ),
        "medium_priority_unscored": _safe_int(
            row.get("medium_priority_unscored")
        ),
        "oldest_unscored_created_at": _safe_datetime(
            row.get("oldest_unscored_created_at")
        ),
        "oldest_eligible_unscored_created_at": _safe_datetime(
            row.get("oldest_eligible_unscored_created_at")
        ),
    }


def _mean_absolute_gaps(
    accuracy_rows: list[dict[str, Any]] | None,
) -> dict[str, tuple[int, float]]:
    """Accumulate per-product-type ``(count, summed gap)`` for scored runs."""
    accums: dict[str, list[float]] = {}
    for raw in accuracy_rows or []:
        if not isinstance(raw, dict):
            continue
        product_type = _safe_str(raw.get("product_type"))
        actual = _safe_float(raw.get("actual_conversion_rate"))
        predicted = predicted_conversion_from_results(
            raw.get("results_json")
        )
        if actual is None or predicted is None:
            continue
        accums.setdefault(product_type, []).append(abs(actual - predicted))
    return {
        product_type: (len(gaps), sum(gaps))
        for product_type, gaps in accums.items()
    }


def _urgency_counts(
    *,
    unscored: int,
    high: int,
    medium: int,
    learning_eligible_unscored: int,
    learning_eligible_only: bool,
) -> dict[str, int]:
    """Derive the HIGH / MEDIUM / LOW urgency distribution for one row."""
    if learning_eligible_only:
        high = min(high, unscored)
        medium = max(0, min(learning_eligible_unscored, unscored) - high)
        low = 0
    else:
        high = min(high, unscored)
        medium = min(medium, max(0, unscored - high))
        low = max(0, unscored - high - medium)
    return {
        URGENCY_HIGH: high,
        URGENCY_MEDIUM: medium,
        URGENCY_LOW: low,
    }


def _recommendation(
    *,
    total_completed: int,
    unscored: int,
    learning_eligible_unscored: int,
    high_priority_unscored: int,
) -> str:
    """Plain-language next step for one product type."""
    if total_completed <= 0:
        return ""
    if unscored <= 0:
        return "All completed runs for this product type have outcome feedback."
    if high_priority_unscored > 0:
        return (
            f"{high_priority_unscored} stale learning-eligible run(s) need "
            "outcome feedback first."
        )
    if learning_eligible_unscored > 0:
        return (
            "Learning-eligible runs remain — scoring them will meaningfully "
            "improve future predictions for this product type."
        )
    return (
        f"{unscored} run(s) still need outcome feedback (below the "
        "learning-weight floor)."
    )


def _narrative(
    *,
    product_type_count: int,
    project_count: int,
    total_completed: int,
    scored: int,
    unscored: int,
    coverage_rate_pct: float,
    learning_eligible_unscored: int,
    high_priority_unscored: int,
    oldest_unscored_age_days: int | None,
    learning_eligible_only: bool,
    weakest: tuple[str, int, int] | None,
) -> str:
    """Compose the one-paragraph coverage-by-product-type narrative."""
    if total_completed == 0:
        return (
            "No completed simulations across your portfolio yet — run one to "
            "generate a prediction you can validate in the real world."
        )
    if scored >= total_completed:
        return (
            "All completed simulations across your portfolio have recorded "
            "outcome feedback — the calibration layer already has everything "
            "it can use from your projects."
        )

    prefix = (
        "Showing learning-eligible unscored runs only. "
        if learning_eligible_only
        else ""
    )
    if unscored == 0 and learning_eligible_only:
        return (
            prefix
            + "No learning-eligible unscored runs remain across your "
            f"portfolio — only {scored} of {total_completed} completed runs "
            "have outcome feedback, and the remaining unscored runs are "
            "below the 0.25 learning-weight floor."
        )

    base = (
        f"Across {product_type_count} product type(s) and {project_count} "
        f"project(s), only {scored} of {total_completed} completed runs have "
        f"outcome feedback ({coverage_rate_pct:.1f}%). "
    )
    if learning_eligible_only:
        base += (
            f"{unscored} unscored learning-eligible run(s) remain."
        )
    else:
        base += (
            f"{unscored} unscored run(s) remain, "
            f"{learning_eligible_unscored} of which would feed calibration "
            "if the product hasn't changed since the run."
        )
    if weakest is not None:
        weakest_type, weakest_scored, weakest_total = weakest
        base += (
            f" Weakest feedback loop: '{weakest_type}' — "
            f"{weakest_scored} of {weakest_total} scored."
        )
    if oldest_unscored_age_days is not None:
        base += (
            f" The oldest unscored run is {oldest_unscored_age_days} days old."
        )
    if high_priority_unscored > 0:
        base += (
            f" {high_priority_unscored} of those are {STALE_DAYS}+ days old "
            "and learning-eligible — score them first."
        )
    return prefix + base


def build_product_type_outcome_gaps_digest(
    *,
    user_id: int,
    coverage_rows: list[dict[str, Any]] | None = None,
    accuracy_rows: list[dict[str, Any]] | None = None,
    learning_eligible_only: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose the product-type outcome-feedback coverage digest.

    Args:
        user_id: owning user primary key (echoed back).
        coverage_rows: per-(project, product-type) coverage aggregate row
            dicts from the route layer. Each row may expose ``product_type``,
            ``project_id``, ``total_completed``, ``scored``, ``unscored``,
            ``learning_eligible_unscored``, ``high_priority_unscored``,
            ``medium_priority_unscored``, ``oldest_unscored_created_at`` and
            ``oldest_eligible_unscored_created_at``.
        accuracy_rows: scored outcome row dicts (``product_type``,
            ``results_json``, ``actual_conversion_rate``) used to compute
            per-type mean absolute prediction error.
        learning_eligible_only: whether the route restricted the unscored
            universe to learning-eligible runs. ``scored`` and
            ``total_completed`` always reflect the full portfolio so
            coverage rates stay honest under filtering.
        now: injected timestamp for deterministic tests.

    Returns:
        A dict matching :class:`ProductTypeOutcomeGapsOut`. Never raises:
        empty or malformed input produces a zeroed digest.
    """
    reference = now or _utcnow()
    by_type: dict[str, dict[str, Any]] = {}
    project_ids: set[int] = set()

    for raw in coverage_rows or []:
        row = _normalise_coverage_row(raw)
        if row is None:
            continue
        product_type = row["product_type"]
        if row["project_id"] > 0:
            project_ids.add(row["project_id"])
        bucket = by_type.setdefault(
            product_type,
            {
                "total_completed": 0,
                "scored": 0,
                "unscored": 0,
                "learning_eligible_unscored": 0,
                "high_priority_unscored": 0,
                "medium_priority_unscored": 0,
                "oldest_unscored_created_at": None,
                "oldest_eligible_unscored_created_at": None,
            },
        )
        for key in (
            "total_completed",
            "scored",
            "unscored",
            "learning_eligible_unscored",
            "high_priority_unscored",
            "medium_priority_unscored",
        ):
            bucket[key] += row[key]
        for source, target in (
            ("oldest_unscored_created_at", "oldest_unscored_created_at"),
            (
                "oldest_eligible_unscored_created_at",
                "oldest_eligible_unscored_created_at",
            ),
        ):
            candidate = row[source]
            current = bucket[target]
            if candidate is not None and (
                current is None or candidate < current
            ):
                bucket[target] = candidate

    gaps = _mean_absolute_gaps(accuracy_rows)
    rows: list[dict[str, Any]] = []
    oldest_ages: list[int] = []
    for product_type, bucket in by_type.items():
        total_completed = bucket["total_completed"]
        scored = bucket["scored"]
        unscored = bucket["unscored"]
        eligible = bucket["learning_eligible_unscored"]
        high = bucket["high_priority_unscored"]
        medium = bucket["medium_priority_unscored"]
        coverage_rate_pct = (
            round((scored / total_completed) * 100.0, 2)
            if total_completed > 0
            else 0.0
        )

        if learning_eligible_only:
            display_unscored = min(unscored, eligible)
            oldest_created = bucket["oldest_eligible_unscored_created_at"]
        else:
            display_unscored = unscored
            oldest_created = bucket["oldest_unscored_created_at"]
        oldest_age = _age_days(oldest_created, reference)
        if oldest_age is not None:
            oldest_ages.append(oldest_age)

        gap_count, gap_sum = gaps.get(product_type, (0, 0.0))
        rows.append(
            {
                "product_type": product_type,
                "total_completed": total_completed,
                "scored": scored,
                "unscored": display_unscored,
                "coverage_rate_pct": coverage_rate_pct,
                "learning_eligible_unscored": eligible,
                "high_priority_unscored": high,
                "oldest_unscored_age_days": oldest_age,
                "urgency_counts": _urgency_counts(
                    unscored=display_unscored,
                    high=high,
                    medium=medium,
                    learning_eligible_unscored=eligible,
                    learning_eligible_only=learning_eligible_only,
                ),
                "mean_absolute_gap": (
                    round(gap_sum / gap_count, 4) if gap_count > 0 else None
                ),
                "scored_with_prediction": gap_count,
                "recommendation": _recommendation(
                    total_completed=total_completed,
                    unscored=display_unscored,
                    learning_eligible_unscored=eligible,
                    high_priority_unscored=high,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            row["coverage_rate_pct"],
            -row["unscored"],
            row["product_type"] == _UNKNOWN_PRODUCT_TYPE,
            row["product_type"],
        )
    )

    total_completed = sum(row["total_completed"] for row in rows)
    scored = sum(row["scored"] for row in rows)
    unscored = sum(row["unscored"] for row in rows)
    eligible = sum(row["learning_eligible_unscored"] for row in rows)
    high = sum(row["high_priority_unscored"] for row in rows)
    coverage_rate_pct = (
        round((scored / total_completed) * 100.0, 2)
        if total_completed > 0
        else 0.0
    )

    weakest: tuple[str, int, int] | None = None
    for row in rows:
        if row["unscored"] > 0 and row["coverage_rate_pct"] < 100.0:
            weakest = (
                row["product_type"],
                row["scored"],
                row["total_completed"],
            )
            break

    summary = {
        "product_type_count": len(rows),
        "project_count": len(project_ids),
        "total_completed": total_completed,
        "scored": scored,
        "unscored": unscored,
        "coverage_rate_pct": coverage_rate_pct,
        "learning_eligible_unscored": eligible,
        "high_priority_unscored": high,
        "oldest_unscored_age_days": max(oldest_ages) if oldest_ages else None,
        "narrative": _narrative(
            product_type_count=len(rows),
            project_count=len(project_ids),
            total_completed=total_completed,
            scored=scored,
            unscored=unscored,
            coverage_rate_pct=coverage_rate_pct,
            learning_eligible_unscored=eligible,
            high_priority_unscored=high,
            oldest_unscored_age_days=(
                max(oldest_ages) if oldest_ages else None
            ),
            learning_eligible_only=learning_eligible_only,
            weakest=weakest,
        ),
    }

    return {
        "user_id": max(0, int(user_id or 0)),
        "generated_at": reference,
        "summary": summary,
        "product_types": rows,
        "learning_eligible_only": learning_eligible_only,
    }


__all__ = ["build_product_type_outcome_gaps_digest"]

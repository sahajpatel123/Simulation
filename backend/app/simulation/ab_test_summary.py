"""
A/B experiment portfolio summary for a project.

The registry endpoints give founders one experiment at a time; this module
rolls every logged experiment up into a single founder-facing digest:

* how many tests have been run and what verdicts they produced;
* whether the challenger (B arm) is beating the control (A arm) overall;
* aggregate traffic / conversion numbers across the whole registry;
* the statistically backed winners worth shipping, plus the tests that are
  trending but still need traffic.

The module is pure (no DB, no I/O): the route passes in the already-loaded
rows and the digest is computed from the denormalised verdict columns, so a
dashboard read stays cheap and one corrupt JSONB snapshot can never break
the summary.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from typing import Any

from app.models.ab_test_experiment import AbTestExperiment
from app.simulation.ab_test_analysis import (
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_SIGNIFICANT,
    VERDICT_TRENDING,
)

# Cap for the top-winner / trending lists — keeps the digest readable.
TOP_N: int = 5

# Founder-facing CTAs, one per digest state. Stable strings so the
# frontend can map a CTA to a button without parsing the payload.
NEXT_ACTION_NO_EXPERIMENTS: str = (
    "Log your first A/B experiment to start building an evidence trail."
)
NEXT_ACTION_SIGNIFICANT_WINNERS: str = (
    "Ship the statistically significant winner(s), then keep recording "
    "real outcomes so the simulation can learn from them."
)
NEXT_ACTION_TRENDING: str = (
    "Keep the trending test(s) running — they are close to significance "
    "but not shippable yet."
)
NEXT_ACTION_MORE_DATA: str = (
    "Gather more traffic before shipping — no test has crossed the "
    "significance threshold yet."
)

# Canonical verdict order for the counts map (stable for the frontend).
_VERDICT_ORDER: tuple[str, ...] = (
    VERDICT_SIGNIFICANT,
    VERDICT_TRENDING,
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT_DATA,
)


def _safe_float(value: Any) -> float | None:
    """Coerce a finite float, returning ``None`` for missing/bad values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _safe_int(value: Any) -> int:
    """Coerce a count to a non-negative int, defaulting to zero."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 6)


def _summary_row(row: AbTestExperiment) -> dict[str, Any]:
    """Render one row for the winners / trending sub-lists."""
    return {
        "id": _safe_int(row.id),
        "name": str(row.name or ""),
        "verdict": str(row.verdict or ""),
        "significant": bool(row.significant),
        "winner": str(row.winner) if row.winner is not None else None,
        "absolute_uplift": _safe_float(row.absolute_uplift),
        "relative_uplift_pct": _safe_float(row.relative_uplift_pct),
        "created_at": row.created_at,
    }


def build_ab_test_summary(
    rows: Sequence[AbTestExperiment],
    project_id: int,
) -> dict[str, Any]:
    """Roll up all logged experiments for a project into one digest.

    Args:
        rows: every ``AbTestExperiment`` row belonging to the project,
            in any order (the digest sorts its own sub-lists).
        project_id: the owning project, echoed back for client routing.

    Returns:
        Dict matching :class:`AbTestExperimentSummaryOut`.
    """
    verdict_counts: dict[str, int] = {
        verdict: 0 for verdict in _VERDICT_ORDER
    }
    total = len(rows)
    significant = 0
    trending = 0
    inconclusive = 0
    insufficient_data = 0
    unclassified = 0
    control_won = 0
    challenger_won = 0
    total_visitors = 0
    total_conversions = 0
    uplifts: list[float] = []
    relative_uplifts: list[float] = []
    top_winners: list[dict[str, Any]] = []
    trending_rows: list[dict[str, Any]] = []

    for row in rows:
        verdict = str(row.verdict or "")
        if verdict in verdict_counts:
            verdict_counts[verdict] += 1
        else:
            unclassified += 1
        if verdict == VERDICT_SIGNIFICANT:
            significant += 1
        elif verdict == VERDICT_TRENDING:
            trending += 1
        elif verdict == VERDICT_INCONCLUSIVE:
            inconclusive += 1
        elif verdict == VERDICT_INSUFFICIENT_DATA:
            insufficient_data += 1

        total_visitors += (
            _safe_int(row.visitors_a) + _safe_int(row.visitors_b)
        )
        total_conversions += (
            _safe_int(row.conversions_a) + _safe_int(row.conversions_b)
        )

        uplift = _safe_float(row.absolute_uplift)
        if uplift is not None:
            uplifts.append(uplift)
            if uplift > 0.0:
                challenger_won += 1
            elif uplift < 0.0:
                control_won += 1

        relative_uplift = _safe_float(row.relative_uplift_pct)
        if relative_uplift is not None:
            relative_uplifts.append(relative_uplift)

        item = _summary_row(row)
        if verdict == VERDICT_SIGNIFICANT:
            top_winners.append(item)
        elif verdict == VERDICT_TRENDING:
            trending_rows.append(item)

    # Best wins first; rows with a missing uplift sort after scored rows.
    top_winners.sort(
        key=lambda item: (
            item["relative_uplift_pct"] is None,
            -(item["relative_uplift_pct"] or 0.0),
        )
    )
    trending_rows.sort(
        key=lambda item: (
            item["absolute_uplift"] is None,
            -(item["absolute_uplift"] or 0.0),
        )
    )

    if total == 0:
        next_action = NEXT_ACTION_NO_EXPERIMENTS
    elif significant > 0:
        next_action = NEXT_ACTION_SIGNIFICANT_WINNERS
    elif trending > 0:
        next_action = NEXT_ACTION_TRENDING
    else:
        next_action = NEXT_ACTION_MORE_DATA

    return {
        "project_id": _safe_int(project_id),
        "total_experiments": total,
        "verdict_counts": verdict_counts,
        "significant_count": significant,
        "trending_count": trending,
        "inconclusive_count": inconclusive,
        "insufficient_data_count": insufficient_data,
        "unclassified_count": unclassified,
        "significant_win_rate": (
            round(significant / total, 6) if total > 0 else None
        ),
        "control_won_count": control_won,
        "challenger_won_count": challenger_won,
        "total_visitors": total_visitors,
        "total_conversions": total_conversions,
        "overall_conversion_rate": (
            round(total_conversions / total_visitors, 6)
            if total_visitors > 0
            else None
        ),
        "mean_absolute_uplift": _mean(uplifts),
        "median_absolute_uplift": _median(uplifts),
        "median_relative_uplift_pct": _median(relative_uplifts),
        "next_action": next_action,
        "top_winners": top_winners[:TOP_N],
        "trending_experiments": trending_rows[:TOP_N],
    }

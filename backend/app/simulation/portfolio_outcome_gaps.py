"""Pure portfolio-level outcome-feedback gaps digest.

The per-project endpoint (``GET /projects/{id}/outcome-gaps``) answers "which
of *this* project's completed runs still need real-world feedback?"; a founder
with several projects still cannot see whether their *portfolio* is closing
the outcome-feedback loop. This module composes the same unscored-run digest
across every owned project:

* Every completed simulation without a matching ``founder_outcomes`` row is
  an open gap; runs whose signal quality meets the calibration learning-weight
  floor are flagged as learning-eligible.
* The per-project rollups are combined into portfolio totals, a coverage rate,
  an oldest-gap age, a high-priority (stale + learning-eligible) count, a
  plain-language narrative, and one row per unscored run.
* The digest is pure Python (no SQL, no I/O), matching the per-project builder,
  so the rollup math is verifiable with plain dicts. Malformed rows are
  tolerated and never raise.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.simulation.outcome_gaps import (
    LEARNING_ELIGIBLE_SIGNAL_QUALITY,
    STALE_DAYS,
    _safe_datetime,
    _safe_int,
    _utcnow,
    age_days,
    build_outcome_gap_item,
)


def _iso(value: Any) -> str:
    """Normalise a value to an ISO-8601 string for stable sorting."""
    parsed = _safe_datetime(value)
    return parsed.isoformat() if parsed is not None else ""


def _normalise_project_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce one raw per-project aggregate row into a safe dict."""
    if not isinstance(row, dict):
        return None
    try:
        project_id = int(row.get("project_id"))
    except (TypeError, ValueError, OverflowError):
        return None
    if project_id <= 0:
        return None
    return {
        "project_id": project_id,
        "total_completed": max(0, _safe_int(row.get("total_completed")) or 0),
        "scored": max(0, _safe_int(row.get("scored")) or 0),
        "unscored": max(0, _safe_int(row.get("unscored")) or 0),
        "learning_eligible_unscored": max(
            0, _safe_int(row.get("learning_eligible_unscored")) or 0
        ),
        "high_priority_unscored": max(
            0, _safe_int(row.get("high_priority_unscored")) or 0
        ),
        "oldest_unscored_created_at": _safe_datetime(
            row.get("oldest_unscored_created_at")
        ),
    }


def _narrative(
    *,
    project_count: int,
    total_completed: int,
    scored: int,
    unscored: int,
    coverage_rate_pct: float,
    learning_eligible_unscored: int,
    high_priority_unscored: int,
    oldest_unscored_age_days: int | None,
    learning_eligible_only: bool,
) -> str:
    """Compose the one-paragraph portfolio outcome-gap narrative."""
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

    if learning_eligible_only:
        base = (
            f"Across {project_count} project(s), only {scored} of "
            f"{total_completed} completed runs have outcome feedback "
            f"({coverage_rate_pct:.1f}%). Scoring the {unscored} unscored "
            "learning-eligible run(s) below teaches the calibration layer "
            "how your predictions hold up in the real world."
        )
    else:
        base = (
            f"Across {project_count} project(s), only {scored} of "
            f"{total_completed} completed runs have outcome feedback "
            f"({coverage_rate_pct:.1f}%). {unscored} unscored run(s) remain, "
            f"{learning_eligible_unscored} of which would feed calibration "
            "if the product hasn't changed since the run."
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


def build_portfolio_outcome_gaps_digest(
    *,
    user_id: int,
    project_rows: list[dict[str, Any]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    limit: int = 50,
    learning_eligible_only: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose the portfolio-level outcome-feedback gaps digest.

    Args:
        user_id: owning user primary key (echoed back).
        project_rows: per-project rollup row dicts. Each row must expose
            ``project_id`` and may expose ``total_completed``, ``scored``,
            ``unscored``, ``learning_eligible_unscored``,
            ``high_priority_unscored`` and ``oldest_unscored_created_at``.
        rows: unscored completed-simulation row dicts for the current page
            (oldest first, from the route layer). Each row may expose
            ``project_id`` in addition to the per-project item fields.
        limit: page size echoed back.
        learning_eligible_only: whether the unscored counts/items were
            restricted to learning-eligible runs by the route layer.
        now: injected timestamp for deterministic tests.

    Returns:
        A dict matching :class:`PortfolioOutcomeGapsOut`. Never raises:
        empty or malformed input produces a zeroed digest.
    """
    reference = now or _utcnow()

    projects: list[dict[str, Any]] = []
    for raw in project_rows or []:
        project = _normalise_project_row(raw)
        if project is None:
            continue
        if project["total_completed"] <= 0 and project["unscored"] <= 0:
            continue
        projects.append(project)
    projects.sort(key=lambda project: project["project_id"])

    total_completed = sum(project["total_completed"] for project in projects)
    scored = sum(project["scored"] for project in projects)
    unscored = sum(project["unscored"] for project in projects)
    learning_eligible_unscored = sum(
        project["learning_eligible_unscored"] for project in projects
    )
    high_priority_unscored = sum(
        project["high_priority_unscored"] for project in projects
    )
    coverage_rate_pct = (
        round((scored / total_completed) * 100.0, 2)
        if total_completed > 0
        else 0.0
    )

    project_payloads: list[dict[str, Any]] = []
    oldest_ages: list[int] = []
    for project in projects:
        oldest_created = project["oldest_unscored_created_at"]
        oldest_age = age_days(oldest_created, reference)
        if oldest_created is not None:
            oldest_ages.append(oldest_age)
        project_payloads.append(
            {
                "project_id": project["project_id"],
                "total_completed": project["total_completed"],
                "scored": project["scored"],
                "unscored": project["unscored"],
                "coverage_rate_pct": (
                    round(
                        (project["scored"] / project["total_completed"]) * 100.0,
                        2,
                    )
                    if project["total_completed"] > 0
                    else 0.0
                ),
                "learning_eligible_unscored": (
                    project["learning_eligible_unscored"]
                ),
                "high_priority_unscored": project["high_priority_unscored"],
                "oldest_unscored_age_days": (
                    oldest_age if oldest_created is not None else None
                ),
            }
        )

    items: list[dict[str, Any]] = []
    sorted_rows = sorted(
        (row for row in (rows or []) if isinstance(row, dict)),
        key=lambda row: (_iso(row.get("created_at")), _safe_int(row.get("simulation_id")) or 0),
    )
    for row in sorted_rows:
        item = build_outcome_gap_item(row, now=reference)
        item["project_id"] = _safe_int(row.get("project_id")) or 0
        items.append(item)

    oldest_unscored_age_days = max(oldest_ages) if oldest_ages else None
    summary = {
        "project_count": len(projects),
        "projects_with_gaps": sum(
            1 for project in projects if project["unscored"] > 0
        ),
        "total_completed": total_completed,
        "scored": scored,
        "unscored": unscored,
        "coverage_rate_pct": coverage_rate_pct,
        "learning_eligible_unscored": learning_eligible_unscored,
        "high_priority_unscored": high_priority_unscored,
        "oldest_unscored_age_days": oldest_unscored_age_days,
        "narrative": _narrative(
            project_count=len(projects),
            total_completed=total_completed,
            scored=scored,
            unscored=unscored,
            coverage_rate_pct=coverage_rate_pct,
            learning_eligible_unscored=learning_eligible_unscored,
            high_priority_unscored=high_priority_unscored,
            oldest_unscored_age_days=oldest_unscored_age_days,
            learning_eligible_only=learning_eligible_only,
        ),
    }

    return {
        "user_id": max(0, int(user_id or 0)),
        "generated_at": reference,
        "summary": summary,
        "projects": project_payloads,
        "items": items,
        "limit": max(1, int(limit or 0)),
        "has_more": unscored > len(items),
        "learning_eligible_only": bool(learning_eligible_only),
    }


__all__ = [
    "LEARNING_ELIGIBLE_SIGNAL_QUALITY",
    "STALE_DAYS",
    "build_portfolio_outcome_gaps_digest",
]

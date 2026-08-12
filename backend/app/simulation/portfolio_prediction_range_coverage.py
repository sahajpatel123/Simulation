"""Pure portfolio-level out-of-sample prediction-range coverage digest.

The per-project coverage endpoint
(``GET /projects/{id}/prediction-range-coverage``) answers "how often did
this project's accuracy-adjusted band contain reality?"; a founder with
several projects still cannot see whether their *portfolio* is calibrated.
This module composes the same out-of-sample checks across every owned
project:

* Every usable outcome is evaluated with only the history available before
  it was recorded, using the same project-first / user-pool fallback as the
  live prediction-range endpoint.
* The per-outcome checks are rolled up into a portfolio coverage rate, mean
  miss margin, worst miss, verdict, narrative, key signals, a per-project
  breakdown, and one row per outcome.
* History selection is shared with the per-project digest, and prefix
  history is maintained incrementally so the whole evaluation is linear in
  the outcome count rather than quadratic.

The module is pure Python (no SQL, no I/O), matching the per-project digest,
so the full out-of-sample behaviour is verifiable with plain dicts.
Malformed row metadata (bad ``id`` / ``simulation_id`` values) is tolerated
and never raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.simulation.prediction_range import (
    LABEL_INSUFFICIENT_DATA,
    MIN_OUTCOMES_FOR_RANGE,
    build_prediction_range,
)
from app.simulation.prediction_range_coverage import (
    _WITHIN_EPSILON,
    MIN_EVALUATED_FOR_VERDICT,
    SIGNAL_CRITICAL,
    SIGNAL_OK,
    SIGNAL_WATCH,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_NEEDS_ATTENTION,
    VERDICT_WELL_CALIBRATED,
    _coverage_verdict,
    _iso,
    _select_history,
    _usable_row,
    _verdict_severity,
)


def _safe_int(value: Any) -> int | None:
    """Coerce a row's ``id`` / ``simulation_id`` to an int, or ``None``.

    Booleans and non-numeric values are treated as missing metadata so a
    malformed row can never crash the digest — ids only order rows and get
    echoed back to the client.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _portfolio_sort_key(row: dict[str, Any]) -> tuple[str, int]:
    """Stable sort key: created_at ascending, id ascending (id tolerant)."""
    return (_iso(row.get("created_at")) or "", _safe_int(row.get("id")) or 0)


def _portfolio_narrative(
    *,
    project_count: int,
    total_outcomes: int,
    evaluated_runs: int,
    within_range_count: int,
    coverage_rate: float | None,
    worst_miss: dict[str, Any] | None,
    verdict: str,
) -> str:
    """Compose the one-paragraph portfolio coverage narrative."""
    if total_outcomes == 0:
        return (
            "No founder outcomes with usable predictions across your "
            "portfolio yet — record outcomes against completed simulations "
            "to verify whether the accuracy-adjusted prediction bands "
            "contain actual conversion."
        )
    if evaluated_runs == 0:
        return (
            f"{total_outcomes} usable outcome(s) across {project_count} "
            f"project(s), but none had enough earlier calibration history "
            f"({MIN_OUTCOMES_FOR_RANGE}+ pairs) to evaluate the prediction "
            "band out-of-sample."
        )
    if verdict == VERDICT_INSUFFICIENT_DATA:
        return (
            f"Only {evaluated_runs} run(s) could be evaluated out-of-sample "
            f"across {project_count} project(s); record at least "
            f"{MIN_EVALUATED_FOR_VERDICT} outcomes to get a band-coverage "
            "verdict."
        )

    pct = coverage_rate * 100.0 if coverage_rate is not None else 0.0
    if verdict == VERDICT_WELL_CALIBRATED:
        tail = (
            "The accuracy-adjusted bands are well calibrated across your "
            "portfolio — keep recording outcomes to maintain the track "
            "record."
        )
    elif verdict == VERDICT_NEEDS_ATTENTION:
        tail = (
            "The bands are directionally useful but miss too often — "
            "review the projects below before relying on the ranges."
        )
    else:
        tail = (
            "The bands rarely contained actual conversion — treat the "
            "ranges as rough bounds and prioritize calibration "
            "improvements."
        )

    sentences = [
        f"Across {evaluated_runs} out-of-sample run(s) and "
        f"{project_count} project(s), the prediction band contained actual "
        f"conversion in {within_range_count} ({pct:.0f}%)."
    ]
    if worst_miss:
        sentences.append(
            f"Worst miss: sim {worst_miss.get('simulation_id') or '?'} with "
            f"actual {worst_miss.get('actual_conversion_rate', 0):.2%} "
            f"outside [{worst_miss.get('low', 0):.2%}, "
            f"{worst_miss.get('high', 0):.2%}]."
        )
    sentences.append(tail)
    return " ".join(sentences)


def build_portfolio_prediction_range_coverage(
    *,
    user_id: int,
    rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the portfolio-level prediction-range coverage digest.

    Args:
        user_id: owning user primary key (echoed back).
        rows: all owned-project outcome row dicts. Each row must expose
            ``project_id``, ``predicted_conversion_rate`` and
            ``actual_conversion_rate``; ``id``, ``simulation_id`` and
            ``created_at`` are optional but recommended for stable ordering
            and row metadata.
        generated_at: ISO timestamp echoed back; defaults to now UTC.

    Returns:
        A dict matching :class:`PortfolioPredictionRangeCoverageOut`. Never
        raises: empty or malformed input produces a zeroed digest.
    """
    usable: list[dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        try:
            project_id = int(raw.get("project_id"))
        except (TypeError, ValueError, OverflowError):
            continue
        if project_id <= 0 or _usable_row(raw) is None:
            continue
        usable.append(raw)
    usable.sort(key=_portfolio_sort_key)

    project_ids = sorted(
        {int(row["project_id"]) for row in usable}
    )

    evaluated_rows: list[dict[str, Any]] = []
    # Incremental prefix history: these lists mirror
    # ``_choose_history(usable[:index], project_id=...)`` at every step
    # without rebuilding both lists from scratch per row, so the digest
    # stays linear in the number of owned outcomes.
    project_prefix_pairs: dict[int, list[tuple[float, float]]] = {}
    user_prefix_pairs: list[tuple[float, float]] = []
    for row in usable:
        project_id = int(row["project_id"])
        predicted, actual = _usable_row(row)
        if predicted is None or actual is None:
            continue

        history, source = _select_history(
            project_prefix_pairs.get(project_id, []),
            user_prefix_pairs,
        )
        simulation_id = _safe_int(row.get("simulation_id"))
        payload = build_prediction_range(
            predicted_conversion_rate=predicted,
            pairs=history,
            simulation_id=simulation_id or 0,
            project_id=project_id,
            calibration_source=source,
        )
        low = payload.get("low")
        high = payload.get("high")
        history_count = int(payload.get("calibration_sample_count") or 0)
        evaluated = (
            history_count >= MIN_OUTCOMES_FOR_RANGE
            and low is not None
            and high is not None
        )
        within: bool | None = None
        margin: float | None = None
        if evaluated and low is not None and high is not None:
            within = (
                actual >= low - _WITHIN_EPSILON
                and actual <= high + _WITHIN_EPSILON
            )
            if within:
                margin = 0.0
            else:
                margin = min(abs(actual - low), abs(actual - high))

        evaluated_rows.append(
            {
                "simulation_id": simulation_id,
                "project_id": project_id,
                "predicted_conversion_rate": predicted,
                "actual_conversion_rate": actual,
                "low": low,
                "high": high,
                "history_count": history_count,
                "calibration_source": source,
                "confidence_label": str(
                    payload.get("confidence_label")
                    or LABEL_INSUFFICIENT_DATA
                ),
                "within": within,
                "margin": round(margin, 6) if margin is not None else None,
                "evaluated": bool(evaluated),
                "created_at": _iso(row.get("created_at")),
            }
        )
        project_prefix_pairs.setdefault(project_id, []).append(
            (predicted, actual)
        )
        user_prefix_pairs.append((predicted, actual))

    checked = [row for row in evaluated_rows if row["evaluated"]]
    within_count = sum(1 for row in checked if row["within"])
    evaluated_count = len(checked)
    coverage_rate = (
        round(within_count / evaluated_count, 6)
        if evaluated_count
        else None
    )
    miss_margins = [
        float(row["margin"])
        for row in checked
        if row["margin"] is not None and row["margin"] > 0.0
    ]
    mean_margin = (
        round(sum(miss_margins) / len(miss_margins), 6)
        if miss_margins
        else None
    )
    worst_miss = (
        max(checked, key=lambda row: float(row["margin"] or -1.0))
        if miss_margins
        else None
    )
    verdict = _coverage_verdict(coverage_rate, evaluated_count)

    total_by_project: dict[int, int] = {}
    for row in usable:
        project_id = int(row["project_id"])
        total_by_project[project_id] = total_by_project.get(project_id, 0) + 1
    evaluated_by_project: dict[int, int] = {}
    within_by_project: dict[int, int] = {}
    for row in evaluated_rows:
        project_id = int(row["project_id"])
        if not row["evaluated"]:
            continue
        evaluated_by_project[project_id] = (
            evaluated_by_project.get(project_id, 0) + 1
        )
        if row["within"]:
            within_by_project[project_id] = (
                within_by_project.get(project_id, 0) + 1
            )

    projects: list[dict[str, Any]] = []
    for project_id in project_ids:
        evaluated = evaluated_by_project.get(project_id, 0)
        within = within_by_project.get(project_id, 0)
        project_coverage = (
            round(within / evaluated, 6) if evaluated else None
        )
        projects.append(
            {
                "project_id": project_id,
                "total_outcomes": total_by_project.get(project_id, 0),
                "evaluated_runs": evaluated,
                "within_range_count": within,
                "coverage_rate": project_coverage,
                "verdict": _coverage_verdict(project_coverage, evaluated),
            }
        )

    key_signals: list[dict[str, Any]] = [
        {
            "label": "evaluated_runs",
            "value": evaluated_count,
            "severity": (
                SIGNAL_WATCH
                if evaluated_count == 0
                else SIGNAL_OK
            ),
            "display": (
                f"{evaluated_count} out-of-sample band check(s) across "
                f"{len(project_ids)} project(s)"
            ),
        }
    ]
    if coverage_rate is not None:
        key_signals.append(
            {
                "label": "coverage_rate",
                "value": coverage_rate,
                "severity": _verdict_severity(verdict),
                "display": (
                    f"Band contained actual conversion in "
                    f"{within_count}/{evaluated_count} "
                    f"({coverage_rate * 100.0:.0f}%)"
                ),
            }
        )
    if mean_margin is not None:
        key_signals.append(
            {
                "label": "mean_miss_margin",
                "value": mean_margin,
                "severity": (
                    SIGNAL_WATCH
                    if mean_margin >= 0.05
                    else SIGNAL_OK
                ),
                "display": f"Mean miss margin {mean_margin * 100.0:.2f}pp",
            }
        )
    if worst_miss:
        key_signals.append(
            {
                "label": "worst_miss_simulation",
                "value": worst_miss.get("simulation_id"),
                "severity": SIGNAL_CRITICAL,
                "display": (
                    f"Worst miss: sim {worst_miss.get('simulation_id') or '?'}"
                ),
            }
        )
    key_signals.append(
        {
            "label": "verdict",
            "value": verdict,
            "severity": _verdict_severity(verdict),
            "display": (
                f"Portfolio band-coverage verdict: "
                f"{verdict.replace('_', ' ').title()}"
            ),
        }
    )

    return {
        "user_id": user_id,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "project_count": len(project_ids),
        "total_outcomes": len(usable),
        "evaluated_runs": evaluated_count,
        "within_range_count": within_count,
        "coverage_rate": coverage_rate,
        "mean_margin": mean_margin,
        "worst_miss": worst_miss,
        "verdict": verdict,
        "narrative": _portfolio_narrative(
            project_count=len(project_ids),
            total_outcomes=len(usable),
            evaluated_runs=evaluated_count,
            within_range_count=within_count,
            coverage_rate=coverage_rate,
            worst_miss=worst_miss,
            verdict=verdict,
        ),
        "key_signals": key_signals,
        "projects": projects,
        "rows": evaluated_rows,
    }


__all__ = [
    "build_portfolio_prediction_range_coverage",
]

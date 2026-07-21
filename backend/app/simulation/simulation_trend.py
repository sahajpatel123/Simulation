"""
Pure helpers for the simulation-trend analytics endpoint.

The route ``GET /projects/{id}/simulation-trend`` issues a single SQL
query for the project's simulations, then hands the rows to
``build_simulation_trend`` which:

  * Builds a per-run history list (with delta + direction tags).
  * Aggregates status counts.
  * Picks best / worst / latest completed runs.
  * Computes mean / median / min / max / std (volatility) across
    conversion rates.
  * Fits a simple linear trend (slope over run-index).
  * Derives a stability score ``1 / (1 + cv)`` where ``cv = std / mean``
    (None when no completed runs).

Keeping this layer pure means the math is verifiable without spinning up
a database.
"""
from __future__ import annotations

from typing import Any

from app.schemas.simulation_trend import RunDetail, RunSummary


def _safe_float(value: Any) -> float:
    """Coerce dict value to float, returning 0.0 on None / bad data."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_results_dict(value: Any) -> dict[str, Any]:
    """
    Defensive: ``results_json`` may arrive as a dict, a JSON string, or
    ``None``. Return a dict either way — empty dict when the payload isn't
    usable.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json as _json

            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def _direction(delta: float | None) -> str | None:
    if delta is None:
        return None
    if delta > 0:
        return "UP"
    if delta < 0:
        return "DOWN"
    return "FLAT"


def _linear_slope(values: list[float]) -> float | None:
    """Simple OLS slope of ``values`` over a 0-indexed x-axis.

    Returns ``None`` when fewer than 2 points are available.
    """
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _stability_score(values: list[float]) -> float | None:
    """Coefficient-of-variation-based stability in [0, 1].

    ``score = 1 / (1 + cv)`` where ``cv = std / mean``. Stable (low cv) → 1,
    volatile (high cv) → 0. Returns None when fewer than 2 points or mean=0.
    """
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    if mean == 0:
        return None
    variance = sum((v - mean) ** 2 for v in values) / n
    std = variance ** 0.5
    cv = std / abs(mean)
    return round(1.0 / (1.0 + cv), 4)


def build_simulation_trend(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
) -> dict[str, Any]:
    """
    Compute the simulation-trend rollup for a project.

    ``rows`` shape (caller has already sorted ascending by ``created_at``):

        [
          {
            "id": int,
            "status": str,
            "signal_quality": float | None,
            "results_json": {"population_weighted_conversion": float} | None,
            "created_at": "2026-..." | None,
          },
          ...
        ]
    """
    history: list[RunSummary] = []
    completed_rates: list[float] = []
    status_breakdown: dict[str, int] = {}
    prev_cr: float | None = None
    best_run: RunDetail | None = None
    worst_run: RunDetail | None = None
    latest_run: RunDetail | None = None

    for row in rows or []:
        status = str(row.get("status") or "UNKNOWN").upper()
        status_breakdown[status] = status_breakdown.get(status, 0) + 1

        results = _coerce_results_dict(row.get("results_json"))
        cr = _safe_float(
            results.get("population_weighted_conversion")
            or results.get("conversion_rate")
            or 0
        )
        delta_cr = round(cr - prev_cr, 4) if prev_cr is not None else None
        created_at = row.get("created_at")
        created_at_str = (
            created_at.isoformat() if hasattr(created_at, "isoformat") else created_at
        )
        run_summary = RunSummary(
            simulation_id=int(row.get("id") or 0),
            status=status,
            signal_quality=_safe_float(row.get("signal_quality")) or None,
            conversion_rate=round(cr, 4),
            delta_from_prev=delta_cr,
            direction=_direction(delta_cr),
            created_at=created_at_str,
        )
        history.append(run_summary)

        if status == "COMPLETED":
            completed_rates.append(cr)
            detail = RunDetail(
                simulation_id=int(row.get("id") or 0),
                conversion_rate=round(cr, 4),
                signal_quality=_safe_float(row.get("signal_quality")) or None,
                created_at=created_at_str,
                status=status,
            )
            if best_run is None or cr > best_run.conversion_rate:
                best_run = detail
            if worst_run is None or cr < worst_run.conversion_rate:
                worst_run = detail
            # Latest completed = last in input order (caller sorts ascending).
            latest_run = detail

        prev_cr = cr

    completed_runs = len(completed_rates)
    conversion_stats: dict[str, float | None] = {
        "count": float(completed_runs),
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "std": None,
    }
    if completed_runs:
        sorted_rates = sorted(completed_rates)
        conversion_stats["min"] = round(min(sorted_rates), 6)
        conversion_stats["max"] = round(max(sorted_rates), 6)
        conversion_stats["mean"] = round(sum(sorted_rates) / completed_runs, 6)
        if completed_runs % 2 == 1:
            median = sorted_rates[completed_runs // 2]
        else:
            median = (
                sorted_rates[completed_runs // 2 - 1]
                + sorted_rates[completed_runs // 2]
            ) / 2.0
        conversion_stats["median"] = round(median, 6)
        if completed_runs > 1:
            mean = conversion_stats["mean"]
            variance = sum((r - mean) ** 2 for r in sorted_rates) / completed_runs
            conversion_stats["std"] = round(variance ** 0.5, 6)

    return {
        "project_id": project_id,
        "total_runs": len(history),
        "completed_runs": completed_runs,
        "status_breakdown": dict(
            sorted(status_breakdown.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
        "history": history,
        "best_run": best_run,
        "worst_run": worst_run,
        "latest_run": latest_run,
        "conversion_stats": conversion_stats,
        "trend_slope": _linear_slope(completed_rates),
        "stability_score": _stability_score(completed_rates),
    }


__all__ = ["build_simulation_trend"]

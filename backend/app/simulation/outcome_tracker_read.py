"""Pure helpers for the per-project conversion-tracking timeline.

The ``outcome_tracker`` table lets founders log lightweight conversion /
revenue checkpoints over time (e.g. week 1 vs week 4 after launch) and see
them against the predicted values from the project's simulation.

This module is pure-Python — the route layer pulls the rows and hands them
to :func:`build_outcome_tracker_timeline`.

Output shape
------------
::

    {
      "project_id": int,
      "total_points": int,
      "points": [
        {
          "id": int,
          "project_id": int,
          "simulation_id": int | None,
          "recorded_at": str | None,
          "actual_conversion_rate": float | None,
          "actual_revenue": float | None,
          "predicted_conversion_rate": float | None,
          "predicted_revenue": float | None,
          "variance": float | None,
          "notes": str | None,
        }
      ],
      "latest_predicted": float | None,
      "latest_actual": float | None,
      "latest_variance_pct": float | None,
      "mean_abs_variance_pct": float | None,
      "bias_direction": "OVER_PREDICTING" | "UNDER_PREDICTING" |
                         "BALANCED" | "INSUFFICIENT_DATA",
    }
"""
from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    """Coerce to finite float or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _variance_pct(
    actual: float | None, predicted: float | None
) -> float | None:
    """Percentage gap ``(actual - predicted) / predicted`` or None."""
    if actual is None or predicted is None or predicted == 0.0:
        return None
    return round((actual - predicted) / abs(predicted) * 100.0, 2)


def build_outcome_tracker_timeline(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
) -> dict[str, Any]:
    """Build the outcome-tracker timeline payload.

    Args:
        rows: list of outcome_tracker row dicts. Each row should contain
            ``id``, ``project_id``, ``simulation_id``, ``recorded_at``,
            ``actual_conversion_rate``, ``actual_revenue``,
            ``predicted_conversion_rate``, ``predicted_revenue``,
            ``variance``, ``notes``. ``recorded_at`` may be a datetime or
            ISO string.
        project_id: owning project id (echoed back).

    Returns:
        Dict matching the shape documented in the module docstring.
    """
    points: list[dict[str, Any]] = []
    variance_values: list[float] = []
    signed_variances: list[float] = []
    latest: dict[str, Any] | None = None

    for raw in rows or []:
        point = {
            "id": int(raw.get("id") or 0),
            "project_id": int(raw.get("project_id") or project_id),
            "simulation_id": (
                int(raw["simulation_id"])
                if raw.get("simulation_id") is not None
                else None
            ),
            "recorded_at": (
                raw["recorded_at"].isoformat()
                if hasattr(raw.get("recorded_at"), "isoformat")
                else raw.get("recorded_at")
            ),
            "actual_conversion_rate": _safe_float(
                raw.get("actual_conversion_rate")
            ),
            "actual_revenue": _safe_float(raw.get("actual_revenue")),
            "predicted_conversion_rate": _safe_float(
                raw.get("predicted_conversion_rate")
            ),
            "predicted_revenue": _safe_float(raw.get("predicted_revenue")),
            "variance": _safe_float(raw.get("variance")),
            "notes": raw.get("notes"),
        }
        points.append(point)
        if point["variance"] is not None:
            variance_values.append(abs(point["variance"]))
            signed_variances.append(point["variance"])
        latest = point

    # Sort ascending so the timeline reads oldest → newest. Rows without a
    # recorded_at stay at the end.
    def _sort_key(p: dict[str, Any]) -> tuple[int, Any]:
        return (0 if p["recorded_at"] is not None else 1, p["recorded_at"])

    points.sort(key=_sort_key)
    latest = points[-1] if points else None

    mean_abs = (
        round(sum(variance_values) / len(variance_values), 2)
        if variance_values
        else None
    )
    if signed_variances:
        mean_signed = sum(signed_variances) / len(signed_variances)
        if abs(mean_signed) < 5.0:
            direction = "BALANCED"
        elif mean_signed < 0:
            direction = "OVER_PREDICTING"
        else:
            direction = "UNDER_PREDICTING"
    else:
        direction = "INSUFFICIENT_DATA"

    return {
        "project_id": project_id,
        "total_points": len(points),
        "points": points,
        "latest_predicted": latest["predicted_conversion_rate"] if latest else None,
        "latest_actual": latest["actual_conversion_rate"] if latest else None,
        "latest_variance_pct": latest["variance"] if latest else None,
        "mean_abs_variance_pct": mean_abs,
        "bias_direction": direction,
    }


__all__ = [
    "_safe_float",
    "_variance_pct",
    "build_outcome_tracker_timeline",
]

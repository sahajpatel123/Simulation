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
      "latest_revenue": float | None,
      "latest_predicted_revenue": float | None,
      "latest_variance_pct": float | None,
      "mean_abs_variance_pct": float | None,
      "bias_direction": "OVER_PREDICTING" | "UNDER_PREDICTING" |
                         "BALANCED" | "INSUFFICIENT_DATA",
    }
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def _safe_float(value: Any) -> float | None:
    """Coerce to finite float or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed) or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _variance_pct(
    actual: float | None, predicted: float | None
) -> float | None:
    """Percentage gap ``(actual - predicted) / predicted`` or None."""
    if actual is None or predicted is None or predicted == 0.0:
        return None
    return round((actual - predicted) / abs(predicted) * 100.0, 2)


def _sort_timestamp(recorded_at: Any) -> datetime | None:
    """Coerce a row's timestamp to a naive UTC datetime for comparison.

    Rows may be ISO strings or ``datetime`` objects (SQLAlchemy returns
    timezone-aware datetimes from PostgreSQL). Mixing aware and naive
    datetimes in a ``sorted`` key comparison raises ``TypeError``, so this
    normalises both to naive UTC. Returns ``None`` for missing or malformed
    timestamps.
    """
    if isinstance(recorded_at, datetime):
        dt = recorded_at
    elif isinstance(recorded_at, str) and recorded_at.strip():
        try:
            dt = datetime.fromisoformat(recorded_at)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


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
    sort_keys: list[tuple[int, datetime]] = []
    variance_values: list[float] = []
    signed_variances: list[float] = []

    for raw in rows or []:
        actual_conv = _safe_float(raw.get("actual_conversion_rate"))
        pred_conv = _safe_float(raw.get("predicted_conversion_rate"))
        stored_variance = _safe_float(raw.get("variance"))
        # Backfill variance for legacy/manually inserted rows so the summary
        # is still meaningful even when the stored column is NULL.
        variance = stored_variance
        if variance is None:
            variance = _variance_pct(actual_conv, pred_conv)

        raw_recorded_at = raw.get("recorded_at")
        recorded_at_dt = (
            _sort_timestamp(raw_recorded_at)
            if raw_recorded_at is not None
            else None
        )
        point = {
            "id": int(raw.get("id") or 0),
            "project_id": int(raw.get("project_id") or project_id),
            "simulation_id": (
                int(raw["simulation_id"])
                if raw.get("simulation_id") is not None
                else None
            ),
            "recorded_at": (
                raw_recorded_at.isoformat()
                if hasattr(raw_recorded_at, "isoformat")
                else raw_recorded_at
            ),
            "actual_conversion_rate": actual_conv,
            "actual_revenue": _safe_float(raw.get("actual_revenue")),
            "predicted_conversion_rate": pred_conv,
            "predicted_revenue": _safe_float(raw.get("predicted_revenue")),
            "variance": variance,
            "notes": raw.get("notes"),
        }
        points.append(point)
        if recorded_at_dt is None:
            sort_keys.append((1, datetime.max.replace(tzinfo=None)))
        else:
            sort_keys.append((0, recorded_at_dt))
        if variance is not None:
            variance_values.append(abs(variance))
            signed_variances.append(variance)

    # Sort ascending so the timeline reads oldest → newest. Rows without a
    # recorded_at stay at the end.
    paired = sorted(zip(sort_keys, points), key=lambda pair: pair[0])
    sort_keys = [pair[0] for pair in paired]
    points = [pair[1] for pair in paired]

    # The latest point is the row with the newest non-null timestamp. A row
    # with a NULL recorded_at must not become the "latest" just because it
    # sorts last.
    latest: dict[str, Any] | None = None
    latest_sort_ts: datetime | None = None
    for sort_key, point in zip(sort_keys, points):
        if sort_key[0] != 0:
            continue
        # Stable tie-break: when two rows share the same timestamp, prefer
        # the later row in sorted order (i.e. the most recently inserted).
        if latest_sort_ts is None or sort_key[1] >= latest_sort_ts:
            latest = point
            latest_sort_ts = sort_key[1]

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
        "latest_revenue": latest["actual_revenue"] if latest else None,
        "latest_predicted_revenue": latest["predicted_revenue"] if latest else None,
        "latest_variance_pct": latest["variance"] if latest else None,
        "mean_abs_variance_pct": mean_abs,
        "bias_direction": direction,
    }


__all__ = [
    "_safe_float",
    "_variance_pct",
    "build_outcome_tracker_timeline",
]

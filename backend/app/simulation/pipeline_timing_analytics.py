"""Pure aggregation helpers for fleet-level pipeline-timing analytics.

The worker now persists ``results_json["pipeline_timing"]`` per run (stage
durations, total, per-agent cost, end-to-end span), but a single run only
tells an operator *that* a run was slow — not whether that is normal for the
fleet, which stage is the usual bottleneck, or which recent runs are the
outliers worth inspecting first.

This module turns a list of persisted timing payloads into a compact
fleet summary:

* per-stage runs / mean / median / p95 / max, plus the mean share each stage
  contributes to total wall-clock (so a stage that is consistently 80% of
  the runtime is easy to spot);
* fleet totals across ``total_seconds``, ``per_agent_ms`` and
  ``end_to_end_seconds``;
* the slowest recent runs, with their dominant stage, for triage.

Pure module - no DB, no I/O. The route supplies the raw rows and the module
normalises malformed / legacy payloads so one bad row cannot poison the
aggregate.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

_RESERVED_SUMMARY_KEYS = frozenset(
    {
        "total_seconds",
        "stage_count",
        "per_agent_ms",
        "end_to_end_seconds",
        "failed_during",
    }
)


def _safe_float(value: Any) -> float | None:
    """Coerce one duration to a finite, non-negative float."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0:
        return None
    return parsed


def _safe_int(value: Any) -> int | None:
    """Coerce a row id to an int, tolerating string / numeric storage."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _coerce_payload(value: Any) -> dict[str, Any] | None:
    """Accept a dict or JSON-encoded string payload; anything else is None."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _coerce_created_at(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile over sorted values (0 <= q <= 1)."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = q * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _clean_stages(payload: dict[str, Any]) -> dict[str, float]:
    """Extract valid stage durations, dropping summary/reserved keys."""
    stages: dict[str, float] = {}
    for name, raw in payload.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or name in _RESERVED_SUMMARY_KEYS
        ):
            continue
        seconds = _safe_float(raw)
        if seconds is not None:
            stages[name] = round(seconds, 4)
    return stages


def _run_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalise one persisted row; ``None`` when it has no usable payload."""
    payload_raw = row.get("pipeline_timing")
    if payload_raw is None and isinstance(row.get("results_json"), dict):
        payload_raw = row["results_json"].get("pipeline_timing")
    payload = _coerce_payload(payload_raw)
    if payload is None:
        return None

    total = _safe_float(payload.get("total_seconds"))
    if total is None:
        return None

    stages = _clean_stages(payload)
    return {
        "simulation_id": _safe_int(row.get("id")) or 0,
        "project_id": _safe_int(row.get("project_id")) or 0,
        "created_at": _coerce_created_at(row.get("created_at")),
        "total_seconds": total,
        "per_agent_ms": _safe_float(payload.get("per_agent_ms")),
        "end_to_end_seconds": _safe_float(payload.get("end_to_end_seconds")),
        "dominant_stage": max(stages, key=stages.get) if stages else None,
        "stages": stages,
    }


def _stage_stats(stage: str, values: list[float], mean_total: float | None) -> dict[str, Any]:
    mean = _mean(values)
    return {
        "stage": stage,
        "runs": len(values),
        "mean_seconds": round(mean, 4) if mean is not None else None,
        "median_seconds": round(_percentile(values, 0.5), 4) if values else None,
        "p95_seconds": round(_percentile(values, 0.95), 4) if values else None,
        "max_seconds": round(max(values), 4) if values else None,
        "mean_share": (
            round(mean / mean_total, 4)
            if mean is not None and mean_total
            else None
        ),
    }


def build_pipeline_timing_summary(
    rows: list[dict[str, Any]] | None,
    *,
    total_completed: int | None = None,
    with_timing: int | None = None,
    sample_limit: int | None = None,
    top_slowest: int = 10,
) -> dict[str, Any]:
    """Build the fleet-level pipeline-timing summary payload.

    Args:
        rows: raw DB rows, each with ``id``, ``project_id``, ``created_at``
            and either ``pipeline_timing`` or a ``results_json`` dict
            containing it. Rows without a usable payload are skipped.
        total_completed: total completed simulations in the fleet (for
            coverage reporting). May be ``None`` when the caller has no
            count query.
        with_timing: completed simulations carrying a timing payload. May
            be ``None``; when both this and ``total_completed`` are set the
            payload includes ``coverage_pct``.
        sample_limit: how many recent rows the caller sampled (purely
            descriptive metadata).
        top_slowest: number of slowest runs to include, ordered by
            ``total_seconds`` descending.

    Returns:
        A dict shaped for ``PipelineTimingSummaryOut``. Never raises:
        malformed rows are dropped, and empty input yields a zeroed summary.
    """
    runs: list[dict[str, Any]] = []
    stage_values: dict[str, list[float]] = {}
    totals: list[float] = []
    per_agent_ms: list[float] = []
    end_to_end: list[float] = []

    for row in rows or []:
        run = _run_from_row(row)
        if run is None:
            continue
        runs.append(run)
        totals.append(run["total_seconds"])
        if run["per_agent_ms"] is not None:
            per_agent_ms.append(run["per_agent_ms"])
        if run["end_to_end_seconds"] is not None:
            end_to_end.append(run["end_to_end_seconds"])
        for stage, seconds in run["stages"].items():
            stage_values.setdefault(stage, []).append(seconds)

    mean_total = _mean(totals)
    stages = [
        _stage_stats(stage, values, mean_total)
        for stage, values in stage_values.items()
    ]
    stages.sort(key=lambda s: (-(s["mean_seconds"] or 0.0), s["stage"]))

    coverage_pct: float | None = None
    if total_completed is not None:
        coverage_pct = 0.0
        if total_completed > 0 and with_timing is not None:
            coverage_pct = round(
                min(float(with_timing), float(total_completed))
                / float(total_completed)
                * 100.0,
                2,
            )

    slowest = sorted(runs, key=lambda r: r["total_seconds"], reverse=True)
    slowest_runs = slowest[: max(0, top_slowest)]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_limit": sample_limit,
        "total_completed": total_completed,
        "with_timing": with_timing,
        "coverage_pct": coverage_pct,
        "runs_analysed": len(runs),
        "totals": {
            "runs": len(totals),
            "mean_seconds": round(mean_total, 4) if mean_total is not None else None,
            "median_seconds": (
                round(_percentile(totals, 0.5), 4) if totals else None
            ),
            "p95_seconds": (
                round(_percentile(totals, 0.95), 4) if totals else None
            ),
            "max_seconds": round(max(totals), 4) if totals else None,
            "sum_seconds": round(sum(totals), 4) if totals else None,
            "mean_per_agent_ms": (
                round(_mean(per_agent_ms), 6) if per_agent_ms else None
            ),
            "p95_per_agent_ms": (
                round(_percentile(per_agent_ms, 0.95), 6) if per_agent_ms else None
            ),
            "mean_end_to_end_seconds": (
                round(_mean(end_to_end), 4) if end_to_end else None
            ),
        },
        "stages": stages,
        "slowest_runs": slowest_runs,
    }


__all__ = ["build_pipeline_timing_summary"]

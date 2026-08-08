"""CSV/JSON export helpers for the journey-trend payload.

The route layer in ``app/api/v1/simulations.py`` already builds the trend
payload through :func:`app.simulation.journey_trend.build_journey_trend`.
This module renders that same payload as a spreadsheet-friendly CSV
(default) or an indented JSON document so founders can bring their funnel
health history into Sheets/Excel, a pitch doc, or a machine pipeline without
writing a parser.

The CSV follows the same multi-section convention as the journey-analytics
and journey-benchmark exports: an optional metadata block, headline trend
statistics, purchase statistics, recent momentum, best/worst runs, the full
per-simulation point series, stage-leak medians, the latest stage leaks, and
the founder-facing insights. Missing or malformed rows degrade to blanks
instead of crashing the export, and every cell is guarded against
spreadsheet formula injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.journey_benchmark import LEAK_STAGE_ORDER

FORMAT_VERSION = "1"


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_text(value: Any) -> str:
    """Render one value as text, normalising ``None`` and booleans."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _safe_float(value: Any) -> float:
    """Parse a finite float, defaulting to ``0.0`` for unusable values."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _safe_int(value: Any) -> int:
    """Parse a finite integer, defaulting to ``0`` for unusable values."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if math.isfinite(parsed) else 0


def _safe_csv_cell(value: Any) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value.lstrip()[:1] in ("=", "+", "-", "@"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not isinstance(metadata, dict) or not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "simulation_id",
        "project_id",
        "format_version",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _purchase_stats_rows(summary: dict[str, Any]) -> list[tuple[str, object]]:
    """Render purchase statistics as ``(metric, value)`` rows."""
    stats = summary.get("purchase_stats") or {}
    if not isinstance(stats, dict):
        return []
    rows: list[tuple[str, object]] = []
    for key in ("count", "min", "max", "mean", "median", "std"):
        value = stats.get(key)
        if key == "count":
            rows.append((key, _safe_int(value)))
        elif value is None:
            rows.append((key, ""))
        else:
            rows.append((key, _safe_float(value)))
    return rows


def _momentum_rows(summary: dict[str, Any]) -> list[tuple[str, object]]:
    """Render recent-momentum counters as ``(metric, value)`` rows."""
    momentum = summary.get("momentum") or {}
    if not isinstance(momentum, dict):
        return []
    rows: list[tuple[str, object]] = []
    for key in (
        "improved_count",
        "declined_count",
        "flat_count",
        "improvement_share_pct",
        "latest_delta",
    ):
        value = momentum.get(key)
        if key in ("improved_count", "declined_count", "flat_count"):
            rows.append((key, _safe_int(value)))
        elif value is None:
            rows.append((key, ""))
        else:
            rows.append((key, _safe_float(value)))
    return rows


def _point_rows(points: list[dict[str, Any]]) -> list[list[object]]:
    """Project each journey point onto a stable column order."""
    rows: list[list[object]] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        rows.append(
            [
                _safe_int(point.get("simulation_id")),
                _safe_int(point.get("project_id")),
                _safe_text(point.get("created_at")),
                _safe_float(point.get("purchase_probability")),
                _safe_float(point.get("abandon_probability")),
                _safe_float(point.get("expected_steps_to_absorb")),
                _safe_float(point.get("expected_revisits")),
                _safe_text(point.get("primary_exit_stage")),
                (
                    _safe_float(point.get("delta_from_prev"))
                    if point.get("delta_from_prev") is not None
                    else ""
                ),
                _safe_text(point.get("direction")),
                _safe_text(point.get("is_anchor")),
            ]
        )
    return rows


def _leak_rows(distribution: Any) -> list[list[object]]:
    """Render a leak dict in deterministic stage order."""
    if not isinstance(distribution, dict):
        return []
    return [
        [stage, _safe_float(distribution.get(stage))]
        for stage in LEAK_STAGE_ORDER
    ]


def journey_trend_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-trend payload as a multi-section CSV string."""
    data = _as_dict(payload)
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if isinstance(metadata, dict) and metadata:
        _write_row(writer, [])

    # Headline trend summary.
    _write_row(writer, ["section", "Headline"])
    _write_row(writer, ["key", "value"])
    for key in (
        "simulation_id",
        "project_id",
        "status",
        "included_count",
        "raw_count",
        "skipped_count",
        "trend_slope",
        "stability_score",
        "anchor_percentile_rank",
        "most_common_primary_exit_stage",
    ):
        value = summary.get(key) if key in summary else data.get(key)
        if key in ("included_count", "raw_count", "skipped_count"):
            _write_row(writer, [key, _safe_int(value)])
        elif key in (
            "trend_slope",
            "stability_score",
            "anchor_percentile_rank",
        ):
            if value is None:
                _write_row(writer, [key, ""])
            else:
                _write_row(writer, [key, _safe_float(value)])
        else:
            _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, [])

    # Purchase statistics.
    _write_row(writer, ["section", "Purchase Statistics"])
    _write_row(writer, ["metric", "value"])
    for key, value in _purchase_stats_rows(summary):
        _write_row(writer, [key, value])
    _write_row(writer, [])

    # Recent momentum.
    _write_row(writer, ["section", "Momentum"])
    _write_row(writer, ["metric", "value"])
    for key, value in _momentum_rows(summary):
        _write_row(writer, [key, value])
    _write_row(writer, [])

    # Best and worst runs.
    _write_row(writer, ["section", "Key Runs"])
    _write_row(
        writer,
        [
            "label",
            "simulation_id",
            "created_at",
            "purchase_probability",
            "primary_exit_stage",
        ],
    )
    for label, point in (
        ("best_point", summary.get("best_point")),
        ("worst_point", summary.get("worst_point")),
    ):
        if isinstance(point, dict):
            _write_row(
                writer,
                [
                    label,
                    _safe_int(point.get("simulation_id")),
                    _safe_text(point.get("created_at")),
                    _safe_float(point.get("purchase_probability")),
                    _safe_text(point.get("primary_exit_stage")),
                ],
            )
        else:
            _write_row(writer, [label, "", "", "", ""])
    _write_row(writer, [])

    # Per-simulation point series.
    _write_row(writer, ["section", "Journey Points"])
    _write_row(
        writer,
        [
            "simulation_id",
            "project_id",
            "created_at",
            "purchase_probability",
            "abandon_probability",
            "expected_steps_to_absorb",
            "expected_revisits",
            "primary_exit_stage",
            "delta_from_prev",
            "direction",
            "is_anchor",
        ],
    )
    points = data.get("points") or []
    point_rows = _point_rows(points if isinstance(points, list) else [])
    if point_rows:
        for row in point_rows:
            _write_row(writer, row)
    else:
        _write_row(writer, ["", "", "", "", "", "", "", "", "", "", ""])
    _write_row(writer, [])

    # Stage-leak medians across all journey-capable simulations.
    _write_row(writer, ["section", "Stage Leak Medians"])
    _write_row(writer, ["stage", "median_probability"])
    median_leaks = _leak_rows(summary.get("stage_leak_medians"))
    if median_leaks:
        for row in median_leaks:
            _write_row(writer, row)
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Latest simulation's stage leaks.
    _write_row(writer, ["section", "Latest Stage Leaks"])
    _write_row(writer, ["stage", "probability"])
    latest_leaks = _leak_rows(summary.get("latest_stage_leaks"))
    if latest_leaks:
        for row in latest_leaks:
            _write_row(writer, row)
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Founder-facing insights.
    _write_row(writer, ["section", "Insights"])
    _write_row(writer, ["rank", "insight"])
    insights = data.get("insights") or []
    if not isinstance(insights, list):
        insights = []
    if insights:
        for rank, insight in enumerate(insights, start=1):
            _write_row(writer, [rank, _safe_text(insight)])
    else:
        _write_row(writer, ["", ""])

    return buffer.getvalue()


def journey_trend_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-trend payload as an indented JSON document."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "journey_trend": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "journey_trend_to_csv",
    "journey_trend_to_json",
]

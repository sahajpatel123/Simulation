"""CSV/JSON export helpers for the journey-analytics payload.

The route layer in ``app/api/v1/simulations.py`` already builds the journey
analytics dict with :func:`build_journey_analytics`. This module renders that
same payload as a spreadsheet-friendly CSV (default) or an indented JSON
document so founders can bring the customer-journey read into Sheets/Excel,
a pitch doc, or a machine pipeline without writing a parser.

The CSV follows the lightweight multi-section convention used elsewhere in
the codebase: an optional metadata block, a headline summary section, the
exit-stage leak table, the most probable paths, the leverage rankings, the
per-cluster detail, and the key insights. Missing or malformed rows degrade
to blanks rather than crashing the export, and every cell is guarded against
spreadsheet formula injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION = "1"

_EXIT_STAGES = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE")
_VISIT_STAGES = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "RETURN")


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
    if not metadata:
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


def journey_analytics_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-analytics payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Headline summary.
    _write_row(writer, ["section", "Headline"])
    _write_row(writer, ["key", "value"])
    for key in (
        "purchase_probability",
        "abandon_probability",
        "expected_steps_to_absorb",
        "expected_revisits",
    ):
        _write_row(writer, [key, _safe_float(data.get(key))])
    meta = data.get("meta") or {}
    if isinstance(meta, dict):
        _write_row(writer, ["matrix_count", meta.get("matrix_count", "")])
        _write_row(writer, ["weighted", _safe_text(meta.get("weighted"))])
    _write_row(writer, [])

    # Exit-stage distribution.
    _write_row(writer, ["section", "Exit Stage Distribution"])
    _write_row(writer, ["stage", "weighted_probability"])
    exit_distribution = data.get("exit_stage_distribution") or {}
    if isinstance(exit_distribution, dict) and exit_distribution:
        for stage in sorted(exit_distribution):
            _write_row(writer, [stage, _safe_float(exit_distribution.get(stage))])
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Most probable paths.
    _write_row(writer, ["section", "Top Paths"])
    _write_row(writer, ["rank", "path", "probability", "converted"])
    top_paths = data.get("top_paths") or []
    if top_paths:
        for rank, path in enumerate(top_paths, start=1):
            if not isinstance(path, dict):
                continue
            _write_row(
                writer,
                [
                    rank,
                    _safe_text(" -> ".join(path.get("path") or [])),
                    _safe_float(path.get("probability")),
                    _safe_text(path.get("converted")),
                ],
            )
    else:
        _write_row(writer, ["", "", "", ""])
    _write_row(writer, [])

    # Leverage rankings.
    _write_row(writer, ["section", "Leverage Rankings"])
    _write_row(
        writer,
        [
            "rank",
            "from_state",
            "to_state",
            "gain_per_5pp",
            "relative_gain_pct",
            "description",
        ],
    )
    leverage_rankings = data.get("leverage_rankings") or []
    if leverage_rankings:
        for rank, item in enumerate(leverage_rankings, start=1):
            if not isinstance(item, dict):
                continue
            _write_row(
                writer,
                [
                    rank,
                    _safe_text(item.get("from_state")),
                    _safe_text(item.get("to_state")),
                    _safe_float(item.get("gain_per_5pp")),
                    _safe_float(item.get("relative_gain_pct")),
                    _safe_text(item.get("description")),
                ],
            )
    else:
        _write_row(writer, ["", "", "", "", "", ""])
    _write_row(writer, [])

    # Per-cluster detail.
    _write_row(writer, ["section", "Per-Cluster"])
    _write_row(
        writer,
        [
            "cluster_id",
            "purchase_probability",
            "expected_steps_to_absorb",
            "primary_exit_stage",
            *[f"exit_{stage}" for stage in _EXIT_STAGES],
            *[f"visits_{stage}" for stage in _VISIT_STAGES],
        ],
    )
    per_cluster = data.get("per_cluster") or []
    if per_cluster:
        for row in per_cluster:
            if not isinstance(row, dict):
                continue
            exits = row.get("exit_stage_distribution") or {}
            visits = row.get("expected_visits_by_stage") or {}
            if not isinstance(exits, dict):
                exits = {}
            if not isinstance(visits, dict):
                visits = {}
            _write_row(
                writer,
                [
                    _safe_text(row.get("cluster_id")),
                    _safe_float(row.get("purchase_probability")),
                    _safe_float(row.get("expected_steps_to_absorb")),
                    _safe_text(row.get("primary_exit_stage")),
                    *[_safe_float(exits.get(stage)) for stage in _EXIT_STAGES],
                    *[_safe_float(visits.get(stage)) for stage in _VISIT_STAGES],
                ],
            )
    else:
        _write_row(
            writer,
            ["", "", "", "", "", "", "", "", "", "", "", "", ""],
        )
    _write_row(writer, [])

    # Key insights.
    _write_row(writer, ["section", "Key Insights"])
    _write_row(writer, ["rank", "insight"])
    key_insights = data.get("key_insights") or []
    if key_insights:
        for rank, insight in enumerate(key_insights, start=1):
            _write_row(writer, [rank, _safe_text(insight)])
    else:
        _write_row(writer, ["", ""])

    return buffer.getvalue()


def journey_analytics_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a journey-analytics payload as an indented JSON document."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "journey_analytics": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "journey_analytics_to_csv",
    "journey_analytics_to_json",
]

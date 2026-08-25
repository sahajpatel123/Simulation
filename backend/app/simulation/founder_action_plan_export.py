"""CSV/JSON export helpers for the founder action plan.

The route layer in ``app/api/v1/simulations.py`` builds a
:class:`app.schemas.founder_action_plan.FounderActionPlanOut` payload; this
module renders that payload as a spreadsheet-friendly CSV (or an indented JSON
document) so founders can bring the ranked, effort-weighted action list into
their planning tools.

The CSV follows the same lightweight multi-section convention as the
unit-economics and simulation exports: an optional metadata block, a
one-row-per-key summary section, one row per action, and an optional meta
key/value section. Missing optional fields render as blanks rather than
crashing the export.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.simulation.export_utils import write_row


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "simulation_id",
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _value(value: Any) -> object:
    return "" if value is None else value


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
    write_row(writer, [_safe_csv_cell(value) for value in row])


def founder_action_plan_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a founder action plan payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Founder Action Plan Summary"])
    _write_row(writer, ["key", "value"])
    summary = _as_dict(data.get("summary"))
    summary_keys = (
        "simulation_id",
        "project_id",
        "status",
        "product_type",
        "headline_conversion",
        "signal_quality",
        "primary_bottleneck",
        "total_actions",
        "total_critical",
        "total_warning",
        "quick_win_count",
        "estimated_total_conversion_impact",
        "verdict",
    )
    for key in summary_keys:
        if key in (
            "total_actions",
            "total_critical",
            "total_warning",
            "quick_win_count",
            "estimated_total_conversion_impact",
            "verdict",
        ):
            _write_row(writer, [key, _value(summary.get(key))])
        else:
            _write_row(writer, [key, _value(data.get(key))])
    _write_row(writer, [])

    # Ranked actions.
    _write_row(writer, ["section", "Ranked Actions"])
    action_keys = (
        "priority",
        "title",
        "summary",
        "domain",
        "stage",
        "metric_affected",
        "source",
        "severity",
        "effort",
        "quick_win_score",
        "estimated_conversion_impact",
        "recommended_action",
        "related_cluster_ids",
    )
    _write_row(writer, list(action_keys))
    for raw_action in data.get("actions") or []:
        action = _as_dict(raw_action) if raw_action is not None else {}
        if not action:
            continue
        related = action.get("related_cluster_ids")
        if related is None:
            related = []
        elif not isinstance(related, (list, tuple, set)):
            # A single cluster identifier (e.g. a string) is one CSV cell
            # rather than being split character-by-character.
            related = [related]
        related_text = "|".join(str(item) for item in related)
        _write_row(
            writer,
            [
                action.get(key) if key != "related_cluster_ids" else related_text
                for key in action_keys
            ],
        )
    _write_row(writer, [])

    # Meta key/value section (optional but useful for provenance).
    meta = _as_dict(data.get("meta") or {})
    if meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _value(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def founder_action_plan_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a founder action plan payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "founder_action_plan": _as_dict(payload)},
        default=str,
        indent=2,
    )


__all__ = [
    "founder_action_plan_to_csv",
    "founder_action_plan_to_json",
]

"""CSV/JSON export helpers for the sensitivity-analysis payload.

The route layer in ``app/api/v1/simulations.py`` computes a
:class:`app.schemas.sensitivity.SensitivityOut` payload; this module
renders that payload as a spreadsheet-friendly CSV so founders can bring
the per-assumption sensitivity ranking into their own planning tools.

The output uses the same lightweight multi-section CSV convention as the
simulation and unit-economics exports: an optional metadata block, a
one-row-per-key summary section, one row per assumption, and the
recommendation list. Missing optional fields render as blanks rather than
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
    """Neutralise spreadsheet formula injection while leaving normal data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas.
    """
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with formula-injection guard applied to every cell."""
    write_row(writer, [_safe_csv_cell(value) for value in row])


def _join_list(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def sensitivity_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a sensitivity-analysis payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Sensitivity Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "simulation_id",
        "project_id",
        "status",
        "signal_quality",
        "product_type_detected",
        "baseline_conversion",
        "baseline_revenue_per_1000",
        "total_assumptions",
        "most_sensitive_assumption",
        "most_sensitive_score",
        "critical_assumptions",
        "high_assumptions",
        "medium_assumptions",
        "low_assumptions",
        "avg_sensitivity_score",
    )
    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    summary_values = {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "signal_quality": data.get("signal_quality"),
        "product_type_detected": data.get("product_type_detected"),
        "baseline_conversion": data.get("baseline_conversion"),
        "baseline_revenue_per_1000": data.get("baseline_revenue_per_1000"),
        "total_assumptions": summary.get("total_assumptions"),
        "most_sensitive_assumption": summary.get("most_sensitive_assumption"),
        "most_sensitive_score": summary.get("most_sensitive_score"),
        "critical_assumptions": summary.get("critical_assumptions"),
        "high_assumptions": summary.get("high_assumptions"),
        "medium_assumptions": summary.get("medium_assumptions"),
        "low_assumptions": summary.get("low_assumptions"),
        "avg_sensitivity_score": summary.get("avg_sensitivity_score"),
    }
    for key in summary_keys:
        _write_row(writer, [key, _value(summary_values.get(key))])
    _write_row(writer, [])

    # Assumption rows.
    _write_row(writer, ["section", "Assumption Sensitivity"])
    _write_row(
        writer,
        [
            "assumption_text",
            "sensitivity",
            "baseline_impact_score",
            "baseline_conversion",
            "max_delta",
            "sensitivity_score",
            "sensitivity_tier",
            "triggers_markov_rules",
            "affected_transitions",
            "recommendation",
        ],
    )
    assumption_keys = (
        "assumption_text",
        "sensitivity",
        "baseline_impact_score",
        "baseline_conversion",
        "max_delta",
        "sensitivity_score",
        "sensitivity_tier",
        "triggers_markov_rules",
        "affected_transitions",
        "recommendation",
    )
    for assumption in data.get("assumptions") or []:
        if not isinstance(assumption, dict):
            continue
        values = [assumption.get(key) for key in assumption_keys]
        values[-2] = _join_list(values[-2])
        _write_row(writer, [_value(value) for value in values])
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(writer, ["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            _write_row(writer, [recommendation])
    else:
        _write_row(writer, [""])

    return buffer.getvalue()


def sensitivity_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a sensitivity-analysis payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "sensitivity": _as_dict(payload)},
        default=str,
        indent=2,
    )


__all__ = ["sensitivity_to_csv", "sensitivity_to_json"]

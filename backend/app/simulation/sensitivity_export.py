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
        writer.writerow([key, value])
    if metadata:
        writer.writerow([])

    # Summary section.
    writer.writerow(["section", "Sensitivity Summary"])
    writer.writerow(["key", "value"])
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
        writer.writerow([key, _value(summary_values.get(key))])
    writer.writerow([])

    # Assumption rows.
    writer.writerow(["section", "Assumption Sensitivity"])
    writer.writerow(
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
        ]
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
        writer.writerow([_value(value) for value in values])
    writer.writerow([])

    # Recommendations.
    writer.writerow(["section", "Recommendations"])
    writer.writerow(["recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for recommendation in recommendations:
            writer.writerow([recommendation])
    else:
        writer.writerow([""])

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

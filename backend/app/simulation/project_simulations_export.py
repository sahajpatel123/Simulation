"""
Pure helper for exporting a project's simulations as CSV.

The route layer pulls the simulation rows and hands them here as dicts;
this module stays deterministic and treats missing fields as empty
strings.
"""
from __future__ import annotations

import csv
import io
import math
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _float(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(parsed):
        return ""
    return f"{parsed:.4f}"


def simulations_to_csv(simulations: list[dict[str, Any]]) -> str:
    """Render simulation dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "simulation_id",
            "project_id",
            "status",
            "created_at",
            "signal_quality",
            "product_type",
            "population_weighted_conversion",
        ]
    )
    for simulation in simulations:
        writer.writerow(
            [
                _text(simulation.get("simulation_id")),
                _text(simulation.get("project_id")),
                _text(simulation.get("status")),
                _text(simulation.get("created_at")),
                _float(simulation.get("signal_quality")),
                _text(simulation.get("product_type")),
                _float(simulation.get("population_weighted_conversion")),
            ]
        )
    return buffer.getvalue()


def simulation_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a simulation-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "simulation_count"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("simulation_count")),
        ]
    )
    return buffer.getvalue()


__all__ = ["simulation_count_to_csv", "simulations_to_csv"]

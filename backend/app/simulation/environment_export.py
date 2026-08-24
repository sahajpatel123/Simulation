"""
Pure helper for exporting a project's environment row as CSV.

The route layer pulls the environment row and hands the dict here; this
module stays deterministic.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def environment_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an environment row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(
        writer,
        [
            "environment_id",
            "project_id",
            "mode",
            "consumer_volume",
            "growth_rate_per_month",
            "average_order_value",
            "price_sensitivity",
            "market_maturity",
            "scenario_type",
            "manual_params_json",
            "trend_data_json",
        ],
    )
    write_row(
        writer,
        [
            _text(row.get("environment_id")),
            _text(row.get("project_id")),
            _text(row.get("mode")),
            _text(row.get("consumer_volume")),
            _text(row.get("growth_rate_per_month")),
            _text(row.get("average_order_value")),
            _text(row.get("price_sensitivity")),
            _text(row.get("market_maturity")),
            _text(row.get("scenario_type")),
            _text(row.get("manual_params_json")),
            _text(row.get("trend_data_json")),
        ],
    )
    return buffer.getvalue()


__all__ = ["environment_to_csv"]

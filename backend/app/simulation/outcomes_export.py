"""
Pure helper for exporting a project's outcome records as CSV.

The route layer pulls the outcome rows and hands them here as dicts;
this module stays deterministic and treats missing fields as empty
strings.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def outcomes_to_csv(outcomes: list[dict[str, Any]]) -> str:
    """Render outcome dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    write_row(
        writer,
        [
            "id",
            "project_id",
            "simulation_id",
            "created_at",
            "actual_conversion_rate",
            "actual_mrr",
            "actual_cac",
            "actual_churn_rate",
            "actual_dau",
            "actual_nps",
            "days_since_launch",
            "notes",
            "predicted_conversion_rate",
            "predicted_mrr",
            "predicted_revenue",
            "variance_conversion",
            "variance_mrr",
            "variance_cac",
            "variance_churn",
            "calibration_score",
        ],
    )
    for outcome in outcomes:
        write_row(
            writer,
            [
                _text(outcome.get("id")),
                _text(outcome.get("project_id")),
                _text(outcome.get("simulation_id")),
                _text(outcome.get("created_at")),
                _text(outcome.get("actual_conversion_rate")),
                _text(outcome.get("actual_mrr")),
                _text(outcome.get("actual_cac")),
                _text(outcome.get("actual_churn_rate")),
                _text(outcome.get("actual_dau")),
                _text(outcome.get("actual_nps")),
                _text(outcome.get("days_since_launch")),
                _text(outcome.get("notes")),
                _text(outcome.get("predicted_conversion_rate")),
                _text(outcome.get("predicted_mrr")),
                _text(outcome.get("predicted_revenue")),
                _text(outcome.get("variance_conversion")),
                _text(outcome.get("variance_mrr")),
                _text(outcome.get("variance_cac")),
                _text(outcome.get("variance_churn")),
                _text(outcome.get("calibration_score")),
            ],
        )
    return buffer.getvalue()


def outcome_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an outcome-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "outcome_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("outcome_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["outcome_count_to_csv", "outcomes_to_csv"]

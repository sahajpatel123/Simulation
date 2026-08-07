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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def outcomes_to_csv(outcomes: list[dict[str, Any]]) -> str:
    """Render outcome dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
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
        ]
    )
    for outcome in outcomes:
        writer.writerow(
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
            ]
        )
    return buffer.getvalue()


__all__ = ["outcomes_to_csv"]

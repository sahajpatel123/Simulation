"""Pure helper for exporting a user's outcomes as CSV."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def user_outcomes_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render user outcome rows as a single CSV table."""
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
            "outcome_id",
            "project_id",
            "actual_conversion_rate",
            "actual_mrr",
            "actual_cac",
            "actual_churn_rate",
            "created_at",
        ],
    )
    for row in rows:
        write_row(
            writer,
            [
                _text(row.get("outcome_id")),
                _text(row.get("project_id")),
                _text(row.get("actual_conversion_rate")),
                _text(row.get("actual_mrr")),
                _text(row.get("actual_cac")),
                _text(row.get("actual_churn_rate")),
                _text(row.get("created_at")),
            ],
        )
    return buffer.getvalue()


__all__ = ["user_outcomes_to_csv"]

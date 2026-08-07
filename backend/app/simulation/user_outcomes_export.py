"""Pure helper for exporting a user's outcomes as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


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
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "outcome_id",
            "project_id",
            "actual_conversion_rate",
            "actual_mrr",
            "actual_cac",
            "actual_churn_rate",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("outcome_id")),
                _text(row.get("project_id")),
                _text(row.get("actual_conversion_rate")),
                _text(row.get("actual_mrr")),
                _text(row.get("actual_cac")),
                _text(row.get("actual_churn_rate")),
                _text(row.get("created_at")),
            ]
        )
    return buffer.getvalue()


__all__ = ["user_outcomes_to_csv"]

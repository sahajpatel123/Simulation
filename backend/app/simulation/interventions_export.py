"""
Pure helper for exporting a project's interventions as CSV.

The route layer pulls ``interventions_json`` from the project and hands
the mode dicts here; this module stays deterministic and treats missing
fields as empty strings.
"""
from __future__ import annotations

import csv
import io
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def interventions_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render intervention dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "list_type",
            "id",
            "title",
            "description",
            "expected_impact",
            "difficulty",
            "estimated_cost",
            "linked_assumption",
            "linked_failure_mode",
            "priority_score",
            "time_to_implement",
            "success_metric",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("list_type")),
                _text(row.get("id")),
                _text(row.get("title")),
                _text(row.get("description")),
                _text(row.get("expected_impact")),
                _text(row.get("difficulty")),
                _text(row.get("estimated_cost")),
                _text(row.get("linked_assumption")),
                _text(row.get("linked_failure_mode")),
                _text(row.get("priority_score")),
                _text(row.get("time_to_implement")),
                _text(row.get("success_metric")),
            ]
        )
    return buffer.getvalue()


__all__ = ["interventions_to_csv"]

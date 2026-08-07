"""
Pure helper for exporting a project's premortem failure modes as CSV.

The route layer pulls ``premortem_json`` from the project and hands the
mode dicts here; this module stays deterministic and treats missing
fields as empty strings.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def premortem_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render premortem failure-mode dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "title",
            "probability",
            "severity",
            "trigger_condition",
            "linked_assumption_texts",
            "intervention",
            "intervention_impact",
            "earliest_signal",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("title")),
                _text(row.get("probability")),
                _text(row.get("severity")),
                _text(row.get("trigger_condition")),
                _text(row.get("linked_assumption_texts")),
                _text(row.get("intervention")),
                _text(row.get("intervention_impact")),
                _text(row.get("earliest_signal")),
            ]
        )
    return buffer.getvalue()


__all__ = ["premortem_to_csv"]

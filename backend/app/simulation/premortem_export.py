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

from app.simulation.export_utils import write_row


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
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(
        writer,
        [
            "title",
            "probability",
            "severity",
            "trigger_condition",
            "linked_assumption_texts",
            "intervention",
            "intervention_impact",
            "earliest_signal",
        ],
    )
    for row in rows:
        write_row(
            writer,
            [
                _text(row.get("title")),
                _text(row.get("probability")),
                _text(row.get("severity")),
                _text(row.get("trigger_condition")),
                _text(row.get("linked_assumption_texts")),
                _text(row.get("intervention")),
                _text(row.get("intervention_impact")),
                _text(row.get("earliest_signal")),
            ],
        )
    return buffer.getvalue()


def premortem_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a premortem-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "premortem_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("premortem_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["premortem_count_to_csv", "premortem_to_csv"]

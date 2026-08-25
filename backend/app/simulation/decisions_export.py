"""
Pure helper for exporting a project's decisions as CSV.

The route layer pulls the decision rows and hands them here as dicts;
this module stays deterministic and treats missing/malformed fields as
empty strings.
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


def decisions_to_csv(
    decisions: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render decision dicts as a single CSV table."""
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
            "id",
            "project_id",
            "title",
            "status",
            "task_id",
            "created_at",
            "result_json",
        ],
    )
    for decision in decisions:
        write_row(
            writer,
            [
                _text(decision.get("id")),
                _text(decision.get("project_id")),
                _text(decision.get("title")),
                _text(decision.get("status")),
                _text(decision.get("task_id")),
                _text(decision.get("created_at")),
                _text(decision.get("result")),
            ],
        )
    return buffer.getvalue()


def decision_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a decision-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "decision_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("decision_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["decision_count_to_csv", "decisions_to_csv"]

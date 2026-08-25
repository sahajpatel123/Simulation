"""
Pure helper for exporting a project's assumptions as CSV.

The route layer pulls the assumption rows and hands them here as dicts;
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


def assumptions_to_csv(
    assumptions: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render assumption dicts as a single CSV table."""
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
            "text",
            "category",
            "sensitivity",
            "impact_score",
            "is_hidden",
            "created_at",
        ],
    )
    for assumption in assumptions:
        write_row(
            writer,
            [
                _text(assumption.get("id")),
                _text(assumption.get("project_id")),
                _text(assumption.get("text")),
                _text(assumption.get("category")),
                _text(assumption.get("sensitivity")),
                _text(assumption.get("impact_score")),
                _text(assumption.get("is_hidden")),
                _text(assumption.get("created_at")),
            ],
        )
    return buffer.getvalue()


def assumption_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an assumption-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "assumption_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("assumption_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["assumption_count_to_csv", "assumptions_to_csv"]

"""Pure helper for exporting a user's simulations as CSV."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.simulation.export_utils import write_row


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def user_simulations_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render user simulation rows as a single CSV table."""
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
            "simulation_id",
            "project_id",
            "status",
            "created_at",
            "signal_quality",
            "product_type",
        ],
    )
    for row in rows:
        write_row(
            writer,
            [
                _text(row.get("simulation_id")),
                _text(row.get("project_id")),
                _text(row.get("status")),
                _text(row.get("created_at")),
                _text(row.get("signal_quality")),
                _text(row.get("product_type")),
            ],
        )
    return buffer.getvalue()


__all__ = ["user_simulations_to_csv"]

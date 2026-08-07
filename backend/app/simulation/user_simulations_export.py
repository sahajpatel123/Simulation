"""Pure helper for exporting a user's simulations as CSV."""
from __future__ import annotations

import csv
import io
from typing import Any


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
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "simulation_id",
            "project_id",
            "status",
            "created_at",
            "signal_quality",
            "product_type",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                _text(row.get("simulation_id")),
                _text(row.get("project_id")),
                _text(row.get("status")),
                _text(row.get("created_at")),
                _text(row.get("signal_quality")),
                _text(row.get("product_type")),
            ]
        )
    return buffer.getvalue()


__all__ = ["user_simulations_to_csv"]

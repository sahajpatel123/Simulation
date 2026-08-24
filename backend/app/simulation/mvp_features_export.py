"""
Pure helper for exporting a project's MVP feature list as CSV.

The route layer pulls ``mvp_feature_list`` from the project and hands
the rows here; this module stays deterministic.
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


def features_to_csv(
    features: list[str],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an MVP feature list as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["index", "feature"])
    for index, feature in enumerate(features, start=1):
        write_row(writer, [index, _text(feature)])
    return buffer.getvalue()


def mvp_feature_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an MVP-feature-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["project_id", "mvp_feature_count"])
    write_row(
        writer,
        [
            _text(row.get("project_id")),
            _text(row.get("mvp_feature_count")),
        ],
    )
    return buffer.getvalue()


__all__ = ["features_to_csv", "mvp_feature_count_to_csv"]

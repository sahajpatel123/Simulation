"""
Pure helper for exporting a project's MVP feature list as CSV.

The route layer pulls ``mvp_feature_list`` from the project and hands
the rows here; this module stays deterministic.
"""
from __future__ import annotations

import csv
import io
from typing import Any


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
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["index", "feature"])
    for index, feature in enumerate(features, start=1):
        writer.writerow([index, _text(feature)])
    return buffer.getvalue()


__all__ = ["features_to_csv"]

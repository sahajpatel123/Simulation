"""CSV export helpers for the calibration-health payload.

The route layer in ``app/api/v1/simulations.py`` already builds the
calibration-health dict with :func:`build_calibration_health`; this module
renders that payload as a spreadsheet-friendly CSV so founders and
operations teams can download the same health check they see on the
dashboard.

The output uses the same lightweight multi-section CSV convention as the
simulation export: an optional metadata block, a one-row-per-key summary
section, a trend-bucket table, and the architect recommendation counts.
Missing optional fields render as blanks rather than crashing the export.
"""

from __future__ import annotations

import csv
import io
from typing import Any


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    values = dict(metadata)
    rows: list[tuple[str, str]] = []
    requested = values.get("requested_ids", "")
    if isinstance(requested, list):
        values["requested_ids"] = ",".join(str(value) for value in requested)
    for key, default in (
        ("generated_at", ""),
        ("user_id", ""),
        ("format_version", "1"),
        ("requested_ids", ""),
    ):
        value = values.get(key, default)
        rows.append((key, "" if value is None else str(value)))
    return rows


def calibration_health_to_csv(
    payload: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a calibration-health payload as a multi-section CSV string."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        writer.writerow([key, value])
    if metadata:
        writer.writerow([])

    # Summary section.
    writer.writerow(["section", "Calibration Summary"])
    writer.writerow(["key", "value"])
    summary_rows: list[tuple[str, object]] = [
        ("overall_health", payload.get("overall_health", "")),
        ("mean_abs_variance", payload.get("mean_abs_variance")),
        ("observation_count", payload.get("observation_count")),
        ("health_trajectory", payload.get("health_trajectory")),
        (
            "consecutive_well_calibrated_days",
            payload.get("consecutive_well_calibrated_days"),
        ),
    ]
    top = payload.get("top_miscalibrated_architect")
    if isinstance(top, dict):
        summary_rows.append(("top_miscalibrated_architect", top.get("architect_name", "")))
        summary_rows.append(
            ("top_miscalibrated_abs_variance", top.get("abs_calibration_variance"))
        )
        summary_rows.append(
            ("top_miscalibrated_recommendation", top.get("recommendation"))
        )
    summary_rows.append(("summary", payload.get("summary", "")))
    for key, value in summary_rows:
        writer.writerow([key, "" if value is None else value])
    writer.writerow([])

    # Trend buckets.
    writer.writerow(["section", "Trend Buckets"])
    writer.writerow(
        ["window", "days", "observation_count", "mean_abs_variance"]
    )
    for bucket in payload.get("trend_buckets") or []:
        if not isinstance(bucket, dict):
            continue
        writer.writerow(
            [
                bucket.get("window", ""),
                bucket.get("days", ""),
                bucket.get("observation_count", ""),
                bucket.get("mean_abs_variance", ""),
            ]
        )
    writer.writerow([])

    # Architect recommendation counts.
    writer.writerow(["section", "Architect Accuracy Counts"])
    writer.writerow(["recommendation", "count"])
    counts = payload.get("architect_accuracy_counts") or {}
    if isinstance(counts, dict) and counts:
        for recommendation in sorted(counts):
            writer.writerow([recommendation, counts[recommendation]])
    else:
        writer.writerow(["", ""])

    return buffer.getvalue()


__all__ = ["calibration_health_to_csv"]

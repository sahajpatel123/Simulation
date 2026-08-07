"""
Pure helper for exporting a project's conversion-tracking timeline as CSV.

The ``outcome_tracker`` table stores lightweight checkpoints a founder logs
over time (conversion / revenue at week 1, week 4, etc.). The timeline
endpoint already renders those rows as JSON; this module gives the same
source rows a deterministic spreadsheet export so founders can drop the
history into Sheets/Excel without building their own parser.

It mirrors ``outcome_tracker_read``:

* Rows are sorted by ``recorded_at`` ascending (oldest first), with rows
  lacking a timestamp at the end.
* Stored ``variance`` is preserved; when the stored column is ``None`` the
  helper backfills the percentage gap ``(actual - predicted) / predicted``
  so exports never silently omit a calibration signal.

No DB / I/O — the route layer pulls the rows and hands them here.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from typing import Any

FORMAT_VERSION = "1"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _variance_pct(actual: Any, predicted: Any) -> float | None:
    """Backfill variance when the stored column is null."""
    actual_f = _safe_float(actual)
    predicted_f = _safe_float(predicted)
    if actual_f is None or predicted_f is None or predicted_f == 0.0:
        return None
    return round((actual_f - predicted_f) / abs(predicted_f) * 100.0, 2)


def _sort_key(recorded_at: Any) -> tuple[int, datetime]:
    """Rows with a real timestamp sort before rows without one."""
    if recorded_at is None or not str(recorded_at).strip():
        return (1, datetime.max.replace(tzinfo=None))
    if isinstance(recorded_at, datetime):
        dt = recorded_at
    else:
        try:
            dt = datetime.fromisoformat(str(recorded_at))
        except (ValueError, TypeError):
            return (1, datetime.max.replace(tzinfo=None))
    if dt.tzinfo is None:
        return (0, dt)
    return (0, dt.astimezone(timezone.utc).replace(tzinfo=None))


def outcome_tracker_to_csv(
    rows: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render conversion-tracking checkpoint dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["project_id", _text(metadata.get("project_id"))])
        if metadata.get("total") is not None:
            writer.writerow(["total", _text(metadata.get("total"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", FORMAT_VERSION))])
        writer.writerow([])

    writer.writerow(
        [
            "id",
            "project_id",
            "simulation_id",
            "recorded_at",
            "actual_conversion_rate",
            "actual_revenue",
            "predicted_conversion_rate",
            "predicted_revenue",
            "variance",
            "notes",
        ]
    )
    for row in sorted(rows or [], key=lambda r: _sort_key(r.get("recorded_at"))):
        actual = row.get("actual_conversion_rate")
        predicted = row.get("predicted_conversion_rate")
        variance = _safe_float(row.get("variance"))
        if variance is None:
            variance = _variance_pct(actual, predicted)
        writer.writerow(
            [
                _text(row.get("id")),
                _text(row.get("project_id")),
                _text(row.get("simulation_id")),
                _text(row.get("recorded_at")),
                _text(actual),
                _text(row.get("actual_revenue")),
                _text(predicted),
                _text(row.get("predicted_revenue")),
                _text(variance),
                _text(row.get("notes")),
            ]
        )
    return buffer.getvalue()


__all__ = ["outcome_tracker_to_csv"]

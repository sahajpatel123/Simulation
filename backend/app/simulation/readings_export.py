"""
Pure helper for exporting a project's readings field as CSV.

The route layer pulls ``readings_json`` from the project and hands the
row here; this module stays deterministic.

``readings_json`` may be a bare JSON array (legacy) or an object with
``readings`` and ``ledger`` keys. Invalid JSON is tolerated and results
in an empty readings table rather than a failed export.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, TypedDict

FORMAT_VERSION = "2"


class ReadingsPayload(TypedDict):
    readings: list[dict[str, str]]
    ledger: dict[str, str]


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _parse_readings_json(raw: Any) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Return ``(readings, ledger)`` from a ``readings_json`` payload.

    Handles the current object shape ``{"readings": [...], "ledger": {...}}``
    and the legacy bare JSON array. Non-dict items and malformed JSON are
    ignored instead of raising, so a corrupted row still exports as an
    empty table.
    """
    if raw is None:
        return [], {}
    if isinstance(raw, dict):
        parsed: Any = raw
    elif isinstance(raw, list):
        parsed = raw
    else:
        try:
            parsed = json.loads(_text(raw))
        except (TypeError, ValueError):
            return [], {}

    if isinstance(parsed, dict):
        readings_raw = parsed.get("readings", [])
        ledger_raw = parsed.get("ledger", {})
    elif isinstance(parsed, list):
        readings_raw = parsed
        ledger_raw = {}
    else:
        return [], {}

    readings: list[dict[str, str]] = []
    if isinstance(readings_raw, list):
        for item in readings_raw:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            body = item.get("body")
            if not isinstance(label, str) and not isinstance(body, str):
                continue
            readings.append(
                {
                    "label": _text(label).strip(),
                    "body": _text(body).strip(),
                }
            )

    ledger: dict[str, str] = {}
    if isinstance(ledger_raw, dict):
        for key in ("deck_line", "section_rubric", "status_rubric", "folio_blurb"):
            value = ledger_raw.get(key)
            if isinstance(value, str) and value.strip():
                ledger[key] = value.strip()
    return readings, ledger


def readings_payload(raw: Any) -> ReadingsPayload:
    """Normalise a project's raw ``readings_json`` for export.

    The CSV helper already tolerates legacy bare arrays, malformed JSON,
    and ``None`` so a corrupted row still exports as an empty table. This
    helper exposes that same parsing so the JSON export path returns the
    same normalised shape instead of echoing whatever string was stored.
    """
    readings, ledger = _parse_readings_json(raw)
    return {"readings": readings, "ledger": ledger}


def readings_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project's readings as CSV tables.

    The metadata section is followed by a one-row-per-reading table and,
    when present, a small ledger table.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(["project_id", _text(row.get("project_id"))])
    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(
            ["format_version", _text(metadata.get("format_version", FORMAT_VERSION))]
        )
        writer.writerow([])

    payload = readings_payload(row.get("readings_json"))
    readings = payload["readings"]
    ledger = payload["ledger"]

    writer.writerow(["index", "label", "body"])
    for index, reading in enumerate(readings, start=1):
        writer.writerow([index, reading["label"], reading["body"]])

    if ledger:
        writer.writerow([])
        writer.writerow(["key", "value"])
        for key in ("deck_line", "section_rubric", "status_rubric", "folio_blurb"):
            value = ledger.get(key)
            if value is not None:
                writer.writerow([key, value])
    return buffer.getvalue()


def readings_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a readings-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _text(metadata.get("user_id"))])
        writer.writerow(["format_version", _text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(["project_id", "readings_count"])
    writer.writerow(
        [
            _text(row.get("project_id")),
            _text(row.get("readings_count")),
        ]
    )
    return buffer.getvalue()


__all__ = ["readings_count_to_csv", "readings_payload", "readings_to_csv"]

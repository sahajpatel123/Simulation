"""CSV, JSON, and Markdown exports for the validation-timeline payload.

The timeline replays every logged experiment chronologically with the
cumulative validation progress after each event.  These exports hand that
replay to a founder's spreadsheet, data pipeline, or weekly report.
Formatting is pure and reuses the exact response payload produced by
``GET /projects/{id}/assumption-validation-timeline``.

CSV is a multi-section document: metadata header, summary, first-occurrence
milestones, one row per evidence event, cumulative progress snapshots, and
per-assumption rollups.  Cells are guarded against spreadsheet formula
injection.  JSON is an envelope with stable metadata and the unmodified
payload.  Markdown is a founder-facing brief with an events table and
milestone list.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "total_assumptions",
    "total_evidence_rows",
)

_MILESTONE_KEYS: tuple[str, ...] = (
    "first_evidence_event_id",
    "last_evidence_event_id",
    "first_de_risked_event_id",
    "first_challenged_event_id",
    "first_inconclusive_event_id",
)

_MILESTONE_LABELS: dict[str, str] = {
    "first_evidence_event_id": "First evidence",
    "last_evidence_event_id": "Last evidence",
    "first_de_risked_event_id": "First de-risked (PASS)",
    "first_challenged_event_id": "First challenged (FAIL)",
    "first_inconclusive_event_id": "First inconclusive",
}

_EVENT_HEADERS: tuple[str, ...] = (
    "event_id",
    "created_at",
    "assumption_id",
    "assumption_text",
    "category",
    "sensitivity",
    "method_label",
    "result",
    "observed_metric",
    "status_after",
    "notes",
)

_PROGRESS_HEADERS: tuple[str, ...] = (
    "event_id",
    "created_at",
    "evidence_rows",
    "assumptions_with_evidence",
    "de_risked_count",
    "challenged_count",
    "inconclusive_count",
    "pending_count",
    "validation_score",
    "evidence_coverage_pct",
)

_ASSUMPTION_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "category",
    "sensitivity",
    "evidence_count",
    "status",
    "first_evidence_event_id",
    "latest_evidence_event_id",
)

# Fraction metrics read best as percentages in the Markdown brief.
_PCT_KEYS: frozenset[str] = frozenset(
    {"validation_score", "evidence_coverage_pct"}
)


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain mapping into a plain dictionary."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _text(value: Any) -> str:
    """Render a scalar for export without leaking Python ``None`` text."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formulas while preserving ordinary values."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped[:1] in ("=", "+", "-", "@") or value[:1] in (
        "\t",
        "\r",
        "\n",
    ):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write one CSV row with the formula guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _json_safe(value: Any) -> Any:
    """Replace non-finite numbers before strict JSON serialisation."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Return stable metadata rows for the top of the CSV document."""
    if not metadata:
        return []
    return [
        (key, _text(metadata.get(key)))
        for key in (
            "generated_at",
            "user_id",
            "project_id",
            "format_version",
        )
    ]


def validation_timeline_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-timeline payload as a multi-section CSV."""
    data = _as_dict(payload)
    milestones = _as_dict(data.get("milestones"))
    events = data.get("events") or []
    progress = data.get("progress") or []
    assumptions = data.get("assumptions") or []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Timeline Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        _write_row(
            writer,
            [key, _text(data.get(key)) if data.get(key) is not None else ""],
        )
    _write_row(writer, [])

    _write_row(writer, ["section", "Milestones"])
    _write_row(writer, ["key", "event_id"])
    for key in _MILESTONE_KEYS:
        value = milestones.get(key)
        _write_row(
            writer,
            [key, _text(value) if value is not None else ""],
        )
    _write_row(writer, [])

    if events:
        _write_row(writer, ["section", "Events"])
        _write_row(writer, list(_EVENT_HEADERS))
        for event in events:
            event_data = _as_dict(event)
            _write_row(
                writer,
                [
                    _text(event_data.get(key))
                    if event_data.get(key) is not None
                    else ""
                    for key in _EVENT_HEADERS
                ],
            )
        _write_row(writer, [])

    if progress:
        _write_row(writer, ["section", "Progress"])
        _write_row(writer, list(_PROGRESS_HEADERS))
        for snapshot in progress:
            snapshot_data = _as_dict(snapshot)
            _write_row(
                writer,
                [
                    _text(snapshot_data.get(key))
                    if snapshot_data.get(key) is not None
                    else ""
                    for key in _PROGRESS_HEADERS
                ],
            )
        _write_row(writer, [])

    if assumptions:
        _write_row(writer, ["section", "Assumptions"])
        _write_row(writer, list(_ASSUMPTION_HEADERS))
        for assumption in assumptions:
            assumption_data = _as_dict(assumption)
            _write_row(
                writer,
                [
                    _text(assumption_data.get(key))
                    if assumption_data.get(key) is not None
                    else ""
                    for key in _ASSUMPTION_HEADERS
                ],
            )
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Timeline Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def validation_timeline_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-timeline payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "validation_timeline": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    """Escape pipe characters so cells can't break Markdown tables."""
    if value is None:
        return ""
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer; empty values render as a dash."""
    if value is None or value == "":
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def _md_pct(value: Any) -> str:
    """Format a 0–1 fraction as a percentage, or a dash when absent."""
    if value is None or value == "":
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{fraction * 100:.1f}%"


def validation_timeline_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-timeline payload as a founder-facing brief."""
    data = _as_dict(payload)
    milestones = _as_dict(data.get("milestones"))
    events = data.get("events") or []

    lines: list[str] = []
    lines.append("# Validation Timeline")
    lines.append("")
    lines.append(
        "Every logged experiment replayed chronologically with the "
        "validation state it left behind."
    )
    lines.append("")

    if metadata:
        generated = _text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    total_assumptions = data.get("total_assumptions")
    total_rows = data.get("total_evidence_rows")
    lines.append(f"| Total assumptions | {_md_cell(total_assumptions)} |")
    lines.append(f"| Evidence rows | {_md_cell(total_rows)} |")
    lines.append("")

    lines.append("## Milestones")
    lines.append("")
    milestone_lines = [
        f"| {_escape_md_cell(_MILESTONE_LABELS[key])} "
        f"| {_md_cell(milestones.get(key))} |"
        for key in _MILESTONE_KEYS
        if milestones.get(key) is not None
    ]
    if milestone_lines:
        lines.append("| Milestone | Event ID |")
        lines.append("| --- | --- |")
        lines.extend(milestone_lines)
    else:
        lines.append("_No milestones yet — log your first experiment._")
    lines.append("")

    if events:
        lines.append("## Events")
        lines.append("")
        lines.append("| When | Assumption | Method | Result | Status after | Notes |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for event in events:
            event_data = _as_dict(event)
            lines.append(
                "| {when} | {assumption} | {method} | {result} | {status} | {notes} |".format(
                    when=_md_cell(event_data.get("created_at")),
                    assumption=_escape_md_cell(
                        str(event_data.get("assumption_text") or "")
                    )
                    or "—",
                    method=_escape_md_cell(
                        str(
                            event_data.get("method_label")
                            or event_data.get("method")
                            or ""
                        )
                    )
                    or "—",
                    result=_md_cell(event_data.get("result")),
                    status=_md_cell(event_data.get("status_after")),
                    notes=_md_cell(event_data.get("notes")),
                )
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Validation timeline"]
    project_id = _text(metadata.get("project_id")) if metadata else ""
    if not project_id:
        project_id = _text(data.get("project_id"))
    if project_id:
        footer.append(f"Project {project_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(
            f"Generated {_escape_md_cell(_text(metadata['generated_at']))}"
        )
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "validation_timeline_to_csv",
    "validation_timeline_to_json",
    "validation_timeline_to_markdown",
]

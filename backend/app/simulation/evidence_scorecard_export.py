"""CSV, JSON, and Markdown exports for the assumption evidence scorecard.

The evidence scorecard (``GET /projects/{project_id}/assumptions/{assumption_id}/evidence-scorecard``)
shows the confidence-upgrade/downgrade arc and how validation-ROI shifts for a
single assumption.  This module renders that payload so a founder can download
it into a spreadsheet, feed a planning pipeline, or read a human-friendly report.

CSV is a multi-section document: an optional metadata block, a one-row-per-key
summary, a per-evidence history table, and a meta section.  Missing optional
fields render as blanks.  The CSV starts with a UTF-8 BOM for Excel compatibility.

JSON is an envelope with stable metadata and the unmodified scorecard payload.

Markdown is a founder-facing brief with a summary table, the assumption details,
the ROI shift (before / after), the evidence history, and a recommendation.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.export_utils import write_row

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "project_id",
    "assumption_id",
    "assumption_text",
    "category",
    "sensitivity",
    "evidence_count",
    "latest_result",
    "derived_confidence",
    "confidence_before",
    "confidence_after",
    "validation_roi_before",
    "validation_roi_after",
    "roi_tier_before",
    "roi_tier_after",
    "roi_delta",
    "tier_upgraded",
    "recommendation",
)

_EVIDENCE_HEADERS: tuple[str, ...] = (
    "id",
    "method_label",
    "result",
    "observed_metric",
    "created_at",
    "derived_confidence",
    "notes",
)


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
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


def _safe_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
    write_row(writer, [_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "assumption_id",
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _json_safe(value: Any) -> Any:
    """Replace non-finite numbers before strict JSON serialisation."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _bool_str(value: Any) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


def evidence_scorecard_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-scorecard payload as a multi-section CSV."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Evidence Scorecard Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        _write_row(writer, [key, _text(data.get(key))])
    _write_row(writer, [])

    # Evidence history.
    _write_row(writer, ["section", "Evidence History"])
    _write_row(writer, list(_EVIDENCE_HEADERS))
    history = data.get("history") or []
    wrote_row = False
    for raw in history:
        exp = _as_dict(raw) if raw is not None else {}
        if not exp:
            continue
        row = [exp.get(key, "") for key in _EVIDENCE_HEADERS]
        _write_row(writer, row)
        wrote_row = True
    if not wrote_row:
        _write_row(writer, [""] * len(_EVIDENCE_HEADERS))
    _write_row(writer, [])

    # Meta section.
    _write_row(writer, ["section", "Meta"])
    _write_row(writer, ["key", "value"])
    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in sorted(meta):
            value = meta[key]
            if isinstance(value, (dict, list)):
                _write_row(writer, [key, json.dumps(value, default=str)])
            else:
                _write_row(writer, [key, _text(value)])

    # UTF-8 BOM: without it, Excel on Windows guesses ANSI and mangles
    # non-Latin assumption text.
    return "\ufeff" + buffer.getvalue()


def evidence_scorecard_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-scorecard payload as an indented JSON envelope."""
    return (
        json.dumps(
            {
                "metadata": _json_safe(metadata or {}),
                "evidence_scorecard": _json_safe(_as_dict(payload)),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


_PCT_LABELS: dict[str, str] = {
    "validation_roi_before": "Validation ROI (before)",
    "validation_roi_after": "Validation ROI (after)",
}

_SUMMARY_LABELS: dict[str, str] = {
    "assumption_text": "Assumption",
    "category": "Category",
    "sensitivity": "Sensitivity",
    "evidence_count": "Evidence count",
    "latest_result": "Latest result",
    "derived_confidence": "Derived confidence",
    "confidence_before": "Confidence (before)",
    "confidence_after": "Confidence (after)",
    "validation_roi_before": "Validation ROI (before)",
    "validation_roi_after": "Validation ROI (after)",
    "roi_tier_before": "ROI tier (before)",
    "roi_tier_after": "ROI tier (after)",
    "roi_delta": "ROI delta",
    "tier_upgraded": "Tier upgraded",
    "recommendation": "Recommendation",
}

_EVIDENCE_COL_LABELS: tuple[str, ...] = (
    "#",
    "Method",
    "Result",
    "Observed",
    "Created",
    "Confidence",
    "Notes",
)


def _escape_md(value: Any) -> str:
    """Escape pipe and newline characters so cells can't break Markdown tables."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    """Format a 0–1 float as a percentage, or return a dash."""
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _escape_md(value)
    return f"{f * 100:.1f}%"


def _md_date(value: Any) -> str:
    """Format a timestamp for Markdown, trimming to date only."""
    if value is None:
        return "—"
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
    return _escape_md(value)


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar summary values."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return "—"
        return str(value)
    return _escape_md(value)


def _summary_cell(key: str, value: Any) -> str:
    """Render one summary cell, applying percentage formatting to ROI values."""
    if key in _PCT_LABELS and isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return _md_pct(value)
    return _md_cell(value)


def evidence_scorecard_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-scorecard payload as a founder-facing brief."""
    data = _as_dict(payload)
    history = data.get("history") or []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    lines: list[str] = []
    lines.append("# Evidence Scorecard")
    lines.append("")
    lines.append(
        "How the latest validation experiment upgraded or challenged a single "
        "assumption, and how the validation-ROI ranking shifted as a result."
    )
    lines.append("")

    if metadata and metadata.get("generated_at"):
        lines.append(f"*Generated: {_escape_md(metadata['generated_at'])}*")
        lines.append("")

    # Assumption identity.
    assumption_text = _escape_md(data.get("assumption_text"))
    if assumption_text:
        lines.append(f"## Assumption: {assumption_text}")
        lines.append("")
    else:
        lines.append("## Assumption")
        lines.append("")

    # Summary table.
    lines.append("## Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for key, label in _SUMMARY_LABELS.items():
        value = data.get(key)
        lines.append(f"| {label} | {_summary_cell(key, value)} |")
    lines.append("")

    # Evidence history table.
    if history:
        lines.append("## Evidence History")
        lines.append("")
        lines.append("| " + " | ".join(_EVIDENCE_COL_LABELS) + " |")
        lines.append("| ---: | --- | --- | ---: | --- | --- | --- |")
        for idx, raw in enumerate(history, start=1):
            row = _as_dict(raw) if raw is not None else {}
            if not row:
                continue
            lines.append(
                f"| {idx} "
                f"| {_escape_md(row.get('method_label', row.get('method', '')))} "
                f"| {_md_cell(row.get('result'))} "
                f"| {_md_cell(row.get('observed_metric'))} "
                f"| {_md_date(row.get('created_at'))} "
                f"| {_md_cell(row.get('derived_confidence'))} "
                f"| {_escape_md(row.get('notes', ''))} |"
            )
        lines.append("")
    else:
        lines.append("## Evidence History")
        lines.append("")
        lines.append("_No validation experiments logged yet._")
        lines.append("")

    # Recommendation.
    recommendation = _escape_md(data.get("recommendation"))
    if recommendation:
        lines.append("## Recommendation")
        lines.append("")
        lines.append(recommendation)
        lines.append("")

    # Meta section.
    if meta:
        lines.append("## Meta")
        lines.append("")
        lines.append("| Key | Value |")
        lines.append("| --- | --- |")
        for key in sorted(meta):
            value = meta[key]
            if isinstance(value, (dict, list)):
                cell = json.dumps(value, default=str, ensure_ascii=False)
            else:
                cell = _escape_md(value)
            lines.append(f"| {key} | {cell} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Evidence scorecard"]
    assumption_id = data.get("assumption_id")
    if assumption_id is not None:
        footer.append(f"Assumption {assumption_id}")
    project_id = data.get("project_id")
    if project_id is not None:
        footer.append(f"Project {project_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(f"Generated {_escape_md(_text(metadata['generated_at']))}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "evidence_scorecard_to_csv",
    "evidence_scorecard_to_json",
    "evidence_scorecard_to_markdown",
]

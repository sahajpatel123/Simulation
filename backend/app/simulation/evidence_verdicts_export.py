"""CSV, JSON, and Markdown exports for the evidence-verdicts payload.

The verdicts endpoint answers *which assumptions are on track, killed, or
self-contradictory*; these exports put the same answer in a founder's
spreadsheet, data pipeline, or weekly validation report. Formatting is
pure and reuses the exact response payload produced by
``GET /projects/{id}/evidence-verdicts``.

CSV is a multi-section document: metadata header, project-level verdict
summary, the full attention-ordered verdict table (one row per
assumption), the next action, and the thresholds used for judging. Cells
are guarded against spreadsheet formula injection so free-form assumption
text stays inert when opened in a spreadsheet. JSON is an envelope with
stable metadata and the unmodified payload. Markdown is a
founder-facing brief with summary and verdict tables.
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
    "judged_count",
    "on_track_count",
    "killed_count",
    "inconsistent_count",
    "unjudged_count",
)

_SUMMARY_LABELS: dict[str, str] = {
    "total_assumptions": "Total assumptions",
    "judged_count": "Judged",
    "on_track_count": "On track",
    "killed_count": "Killed",
    "inconsistent_count": "Inconsistent",
    "unjudged_count": "Unjudged",
}

_ROW_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "category",
    "evidence_count",
    "latest_result",
    "latest_method",
    "method_label",
    "threshold",
    "observed_metric",
    "margin_pp",
    "verdict",
    "explanation",
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


def evidence_verdicts_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-verdicts payload as a multi-section CSV."""
    data = _as_dict(payload)
    rows = data.get("rows") or []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Verdict Summary"])
    _write_row(writer, ["key", "value"])
    for key in _SUMMARY_KEYS:
        value = data.get(key)
        _write_row(writer, [key, _text(value) if value is not None else ""])
    _write_row(writer, [])

    _write_row(writer, ["section", "Assumption Verdicts"])
    _write_row(writer, list(_ROW_HEADERS))
    for raw_row in rows:
        item = _as_dict(raw_row)
        if not item:
            continue
        _write_row(
            writer,
            [_text(item.get(key, "")) for key in _ROW_HEADERS],
        )
    _write_row(writer, [])

    next_action = data.get("next_action")
    if next_action:
        _write_row(writer, ["section", "Next Action"])
        _write_row(writer, [next_action])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Verdicts Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def evidence_verdicts_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-verdicts payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "evidence_verdicts": _json_safe(_as_dict(payload)),
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


def _md_pct(value: Any) -> str:
    """Format a 0–1 float as a percentage, or return a dash."""
    if value is None:
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{fraction * 100:.1f}%"


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def _md_margin(value: Any) -> str:
    """Format a margin in percentage points with an explicit sign."""
    if value is None:
        return "—"
    try:
        margin = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{margin:+.2f}pp"


def evidence_verdicts_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render an evidence-verdicts payload as a founder-facing brief."""
    data = _as_dict(payload)
    rows = data.get("rows") or []

    lines: list[str] = []
    lines.append("# Evidence Verdicts")
    lines.append("")
    lines.append(
        "Each assumption's latest decisive experiment judged against its "
        "method's success bar — on track, killed, or contradicting its own "
        "record."
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
    for key in _SUMMARY_KEYS:
        lines.append(
            f"| {_escape_md_cell(_SUMMARY_LABELS.get(key, key))} "
            f"| {_md_cell(data.get(key))} |"
        )
    lines.append("")

    if rows:
        lines.append("## Verdicts")
        lines.append("")
        lines.append(
            "| # | Assumption | Category | Evidence | Latest | Method "
            "| Bar | Observed | Margin | Verdict |"
        )
        lines.append("| ---: | --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- |")
        for idx, raw_row in enumerate(rows, start=1):
            item = _as_dict(raw_row)
            if not item:
                continue
            lines.append(
                f"| {idx} "
                f"| {_escape_md_cell(item.get('assumption_text', ''))} "
                f"| {_escape_md_cell(item.get('category', ''))} "
                f"| {_md_cell(item.get('evidence_count', 0))} "
                f"| {_escape_md_cell(item.get('latest_result') or '—')} "
                f"| {_escape_md_cell(item.get('method_label') or '—')} "
                f"| {_md_pct(item.get('threshold'))} "
                f"| {_md_pct(item.get('observed_metric'))} "
                f"| {_md_margin(item.get('margin_pp'))} "
                f"| {_escape_md_cell(item.get('verdict', ''))} |"
            )
        lines.append("")

    next_action = data.get("next_action")
    if next_action:
        lines.append("## Next Action")
        lines.append("")
        lines.append(f"**{_escape_md_cell(next_action)}**")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Evidence verdicts"]
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
    "evidence_verdicts_to_csv",
    "evidence_verdicts_to_json",
    "evidence_verdicts_to_markdown",
]

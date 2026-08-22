"""CSV, JSON, and Markdown exports for the validation dashboard.

The validation dashboard is intentionally compact for a polling UI, but its
nested digest, milestones, and forecast are also useful in a founder's
spreadsheet or planning pipeline.  This module keeps export formatting pure
and reuses the exact response payload produced by the dashboard endpoint.

CSV is a multi-section document containing the dashboard summary, validation
milestones, assumption-level rows, result/method histograms, and metadata.
Cells are guarded against spreadsheet formula injection so free-form
assumption text and founder notes remain inert when opened in a spreadsheet.
JSON is an envelope with stable metadata and the unmodified dashboard data.
Markdown is a founder-facing brief suitable for docs, Notion, or a weekly
validation report.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "project_id",
    "total_assumptions",
    "total_evidence_rows",
    "assumptions_with_evidence",
    "evidence_coverage_pct",
    "de_risked_count",
    "challenged_count",
    "inconclusive_count",
    "pending_count",
    "validation_score",
    "next_action",
    "momentum_trend",
    "overall_events_per_week",
    "recent_events_per_week",
    "coverage_velocity_per_week",
    "de_risk_velocity_per_week",
    "target_de_risked_pct",
    "target_de_risked_count",
    "remaining_for_coverage",
    "remaining_for_target",
    "weeks_to_full_coverage",
    "projected_full_coverage_at",
    "weeks_to_de_risked_target",
    "projected_de_risked_at",
    "forecast_confident",
)

_ASSUMPTION_HEADERS: tuple[str, ...] = (
    "assumption_id",
    "assumption_text",
    "category",
    "sensitivity",
    "evidence_count",
    "latest_result",
    "derived_confidence",
    "status",
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


def _summary_rows(data: dict[str, Any]) -> list[tuple[str, object]]:
    """Flatten the nested dashboard into founder-friendly summary rows."""
    digest = _as_dict(data.get("evidence_digest"))
    momentum = _as_dict(data.get("momentum"))
    velocity = _as_dict(momentum.get("velocity"))
    forecast = _as_dict(momentum.get("forecast"))

    values: dict[str, Any] = {
        "project_id": data.get("project_id", digest.get("project_id")),
        "total_assumptions": digest.get("total_assumptions"),
        "total_evidence_rows": digest.get("total_evidence_rows"),
        "assumptions_with_evidence": digest.get("assumptions_with_evidence"),
        "evidence_coverage_pct": digest.get("evidence_coverage_pct"),
        "de_risked_count": digest.get("de_risked_count"),
        "challenged_count": digest.get("challenged_count"),
        "inconclusive_count": digest.get("inconclusive_count"),
        "pending_count": digest.get("pending_count"),
        "validation_score": digest.get("validation_score"),
        "next_action": digest.get("next_action"),
        "momentum_trend": velocity.get("trend"),
        "overall_events_per_week": velocity.get("overall_events_per_week"),
        "recent_events_per_week": velocity.get("recent_events_per_week"),
        "coverage_velocity_per_week": velocity.get("coverage_velocity_per_week"),
        "de_risk_velocity_per_week": velocity.get("de_risk_velocity_per_week"),
        "target_de_risked_pct": forecast.get("target_de_risked_pct"),
        "target_de_risked_count": forecast.get("target_de_risked_count"),
        "remaining_for_coverage": forecast.get("remaining_for_coverage"),
        "remaining_for_target": forecast.get("remaining_for_target"),
        "weeks_to_full_coverage": forecast.get("weeks_to_full_coverage"),
        "projected_full_coverage_at": forecast.get("projected_full_coverage_at"),
        "weeks_to_de_risked_target": forecast.get("weeks_to_de_risked_target"),
        "projected_de_risked_at": forecast.get("projected_de_risked_at"),
        "forecast_confident": forecast.get("confident"),
    }
    return [(key, values.get(key)) for key in _SUMMARY_KEYS]


def _mapping_rows(values: Any) -> list[tuple[str, object]]:
    """Render a histogram mapping in deterministic key order."""
    if not isinstance(values, dict):
        return []
    return [(str(key), value) for key, value in sorted(values.items())]


def validation_dashboard_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-dashboard payload as a multi-section CSV."""
    data = _as_dict(payload)
    digest = _as_dict(data.get("evidence_digest"))
    milestones = _as_dict(data.get("timeline_milestones"))

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Validation Dashboard Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_rows(data):
        _write_row(writer, [key, _text(value) if value is not None else ""])
    _write_row(writer, [])

    _write_row(writer, ["section", "Validation Milestones"])
    _write_row(writer, ["key", "event_id"])
    for key in (
        "first_evidence_event_id",
        "last_evidence_event_id",
        "first_de_risked_event_id",
        "first_challenged_event_id",
        "first_inconclusive_event_id",
    ):
        _write_row(writer, [key, milestones.get(key, "")])
    _write_row(writer, [])

    _write_row(writer, ["section", "Assumptions"])
    _write_row(writer, list(_ASSUMPTION_HEADERS))
    for raw_assumption in digest.get("assumptions") or []:
        assumption = _as_dict(raw_assumption)
        if not assumption:
            continue
        _write_row(
            writer,
            [assumption.get(key, "") for key in _ASSUMPTION_HEADERS],
        )
    _write_row(writer, [])

    for title, key in (
        ("Result Counts", "result_counts"),
        ("Method Counts", "method_counts"),
    ):
        _write_row(writer, ["section", title])
        _write_row(writer, ["key", "count"])
        for count_key, count in _mapping_rows(digest.get(key)):
            _write_row(writer, [count_key, count])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Dashboard Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def validation_dashboard_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-dashboard payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "validation_dashboard": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


# Summary metrics stored as 0–1 fractions but read best as percentages in
# the founder-facing Markdown brief (CSV keeps the raw numbers).
_PCT_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "evidence_coverage_pct",
        "validation_score",
        "target_de_risked_pct",
    }
)

_SUMMARY_LABELS: dict[str, str] = {
    "project_id": "Project ID",
    "total_assumptions": "Total assumptions",
    "total_evidence_rows": "Evidence rows",
    "assumptions_with_evidence": "Assumptions with evidence",
    "evidence_coverage_pct": "Evidence coverage",
    "target_de_risked_pct": "De-risk target share",
    "target_de_risked_count": "De-risk target count",
    "de_risked_count": "De-risked",
    "challenged_count": "Challenged",
    "inconclusive_count": "Inconclusive",
    "pending_count": "Pending",
    "validation_score": "Validation score",
    "momentum_trend": "Cadence trend",
    "overall_events_per_week": "Overall experiments/week",
    "recent_events_per_week": "Recent experiments/week",
    "coverage_velocity_per_week": "Coverage velocity (/week)",
    "de_risk_velocity_per_week": "De-risking velocity (/week)",
    "remaining_for_coverage": "Remaining for full coverage",
    "remaining_for_target": "Remaining for de-risked target",
    "weeks_to_full_coverage": "Weeks to full coverage",
    "projected_full_coverage_at": "Projected full coverage",
    "weeks_to_de_risked_target": "Weeks to de-risked target",
    "projected_de_risked_at": "Projected de-risk target",
    "forecast_confident": "Forecast confident",
    "next_action": "Next action",
}

_MILESTONE_LABELS: dict[str, str] = {
    "first_evidence_event_id": "First evidence",
    "last_evidence_event_id": "Last evidence",
    "first_de_risked_event_id": "First de-risked (PASS)",
    "first_challenged_event_id": "First challenged (FAIL)",
    "first_inconclusive_event_id": "First inconclusive",
}

_MILESTONE_KEYS: tuple[str, ...] = tuple(_MILESTONE_LABELS.keys())


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
        f = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    return f"{f * 100:.1f}%"


def _md_bool(value: Any) -> str:
    if value is None:
        return "—"
    return "yes" if value else "no"


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar summary values."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return _md_bool(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return "—"
        return str(value)
    text = str(value)
    return _escape_md_cell(text)


def validation_dashboard_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-dashboard payload as a founder-facing brief."""
    data = _as_dict(payload)
    digest = _as_dict(data.get("evidence_digest"))
    milestones = _as_dict(data.get("timeline_milestones"))
    summary_rows = dict(_summary_rows(data))

    lines: list[str] = []
    lines.append("# Validation Dashboard")
    lines.append("")
    lines.append(
        "De-risking overview combining evidence coverage, first-occurrence "
        "milestones, and the projected validation horizon."
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
        if key not in summary_rows:
            continue
        value = summary_rows[key]
        rendered = (
            _md_pct(value) if key in _PCT_SUMMARY_KEYS else _md_cell(value)
        )
        lines.append(
            f"| {_escape_md_cell(_SUMMARY_LABELS.get(key, key))} "
            f"| {rendered} |"
        )
    lines.append("")

    lines.append("## Validation Milestones")
    lines.append("")
    lines.append("| Milestone | Event ID |")
    lines.append("| --- | --- |")
    for key in _MILESTONE_KEYS:
        event_id = milestones.get(key)
        rendered = (
            _escape_md_cell(event_id) if event_id is not None else "—"
        )
        lines.append(f"| {_MILESTONE_LABELS[key]} | {rendered} |")
    lines.append("")

    assumptions = digest.get("assumptions") or []
    if assumptions:
        lines.append("## Assumptions")
        lines.append("")
        header = (
            "| # | Assumption | Category | Sensitivity | Evidence | "
            "Latest | Confidence | Status |"
        )
        lines.append(header)
        lines.append("| ---: | --- | --- | --- | ---: | --- | --- | --- |")
        for idx, raw in enumerate(assumptions, start=1):
            assumption = _as_dict(raw)
            if not assumption:
                continue
            lines.append(
                f"| {idx} | {_escape_md_cell(assumption.get('assumption_text', ''))} "
                f"| {_escape_md_cell(assumption.get('category', ''))} "
                f"| {_escape_md_cell(assumption.get('sensitivity', ''))} "
                f"| {_md_cell(assumption.get('evidence_count', 0))} "
                f"| {_md_cell(assumption.get('latest_result'))} "
                f"| {_md_cell(assumption.get('derived_confidence'))} "
                f"| {_md_cell(assumption.get('status'))} |"
            )
        lines.append("")

    result_counts = digest.get("result_counts")
    if isinstance(result_counts, dict):
        lines.append("## Result Counts")
        lines.append("")
        lines.append("| Result | Count |")
        lines.append("| --- | ---: |")
        for key, value in sorted(result_counts.items()):
            lines.append(f"| {_escape_md_cell(key)} | {value or 0} |")
        lines.append("")

    method_counts = digest.get("method_counts")
    if isinstance(method_counts, dict):
        lines.append("## Method Counts")
        lines.append("")
        lines.append("| Method | Count |")
        lines.append("| --- | ---: |")
        for key, value in sorted(method_counts.items()):
            lines.append(f"| {_escape_md_cell(key)} | {value or 0} |")
        lines.append("")

    next_action = _text(summary_rows.get("next_action"))
    if next_action:
        lines.append("## Next Action")
        lines.append("")
        lines.append(_escape_md_cell(next_action))
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Validation dashboard"]
    project_id = _text(summary_rows.get("project_id"))
    if project_id:
        footer.append(f"Project {project_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(f"Generated {_escape_md_cell(_text(metadata['generated_at']))}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "validation_dashboard_to_csv",
    "validation_dashboard_to_json",
    "validation_dashboard_to_markdown",
]

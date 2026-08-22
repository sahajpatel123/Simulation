"""CSV, JSON, and Markdown exports for the validation-momentum payload.

Momentum answers *how fast* validation is happening and *when it will
finish*; these exports put that answer in a founder's spreadsheet, data
pipeline, or weekly report.  Formatting is pure and reuses the exact
response payload produced by ``GET /projects/{id}/validation-momentum``.

CSV is a multi-section document: metadata header, coverage/de-risking
counts, velocity metrics, forecast projection, and insights.  Cells are
guarded against spreadsheet formula injection.  JSON is an envelope with
stable metadata and the unmodified payload.  Markdown is a founder-facing
brief with one table per section and insight bullets.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_COUNT_KEYS: tuple[str, ...] = (
    "total_assumptions",
    "total_evidence_rows",
    "assumptions_with_evidence",
    "de_risked_count",
    "challenged_count",
    "inconclusive_count",
    "pending_count",
    "evidence_coverage_pct",
    "validation_score",
)

_VELOCITY_KEYS: tuple[str, ...] = (
    "trend",
    "overall_events_per_week",
    "recent_events_per_week",
    "recent_window_days",
    "events_last_28_days",
    "first_evidence_at",
    "latest_evidence_at",
    "evidence_span_days",
    "coverage_velocity_per_week",
    "de_risk_velocity_per_week",
)

_FORECAST_KEYS: tuple[str, ...] = (
    "target_de_risked_pct",
    "target_de_risked_count",
    "remaining_for_coverage",
    "remaining_for_target",
    "weeks_to_full_coverage",
    "projected_full_coverage_at",
    "weeks_to_de_risked_target",
    "projected_de_risked_at",
    "confident",
)

# Fraction metrics read best as percentages in the Markdown brief.
_PCT_KEYS: frozenset[str] = frozenset(
    {
        "target_de_risked_pct",
        "evidence_coverage_pct",
        "validation_score",
    }
)

_LABELS: dict[str, str] = {
    # Counts
    "total_assumptions": "Total assumptions",
    "total_evidence_rows": "Evidence rows",
    "assumptions_with_evidence": "Assumptions with evidence",
    "de_risked_count": "De-risked",
    "challenged_count": "Challenged",
    "inconclusive_count": "Inconclusive",
    "pending_count": "Pending",
    "evidence_coverage_pct": "Coverage",
    "validation_score": "Validation score",
    # Velocity
    "trend": "Cadence trend",
    "overall_events_per_week": "Experiments/week (overall)",
    "recent_events_per_week": "Experiments/week (recent)",
    "recent_window_days": "Recent window (days)",
    "events_last_28_days": "Events in recent window",
    "first_evidence_at": "First evidence",
    "latest_evidence_at": "Latest evidence",
    "evidence_span_days": "Evidence span (days)",
    "coverage_velocity_per_week": "Coverage velocity (/week)",
    "de_risk_velocity_per_week": "De-risking velocity (/week)",
    # Forecast
    "target_de_risked_pct": "De-risk target share",
    "target_de_risked_count": "De-risk target count",
    "remaining_for_coverage": "Remaining for full coverage",
    "remaining_for_target": "Remaining for target",
    "weeks_to_full_coverage": "Weeks to full coverage",
    "projected_full_coverage_at": "Projected full coverage",
    "weeks_to_de_risked_target": "Weeks to target",
    "projected_de_risked_at": "Projected target date",
    "confident": "Forecast confident",
}


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


def validation_momentum_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-momentum payload as a multi-section CSV."""
    data = _as_dict(payload)
    counts = _as_dict(data.get("counts"))
    velocity = _as_dict(data.get("velocity"))
    forecast = _as_dict(data.get("forecast"))
    insights = data.get("insights") or []

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    for title, section_keys, section in (
        ("Momentum Counts", _COUNT_KEYS, counts),
        ("Velocity", _VELOCITY_KEYS, velocity),
        ("Forecast", _FORECAST_KEYS, forecast),
    ):
        _write_row(writer, ["section", title])
        _write_row(writer, ["key", "value"])
        for key in section_keys:
            value = section.get(key)
            _write_row(
                writer,
                [key, _text(value) if value is not None else ""],
            )
        _write_row(writer, [])

    if insights:
        _write_row(writer, ["section", "Insights"])
        for text in insights:
            _write_row(writer, [text])
        _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Momentum Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def validation_momentum_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-momentum payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "validation_momentum": _json_safe(_as_dict(payload)),
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


def _md_section(lines: list[str], title: str, keys: tuple[str, ...], section: dict[str, Any]) -> None:
    """Append one Metric/Value Markdown table for the given keys."""
    lines.append(f"## {title}")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for key in keys:
        value = section.get(key)
        rendered = _md_pct(value) if key in _PCT_KEYS else _md_cell(value)
        lines.append(
            f"| {_escape_md_cell(_LABELS.get(key, key))} | {rendered} |"
        )
    lines.append("")


def validation_momentum_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-momentum payload as a founder-facing brief."""
    data = _as_dict(payload)
    counts = _as_dict(data.get("counts"))
    velocity = _as_dict(data.get("velocity"))
    forecast = _as_dict(data.get("forecast"))
    insights = data.get("insights") or []

    lines: list[str] = []
    lines.append("# Validation Momentum")
    lines.append("")
    lines.append(
        "How fast validation is moving — evidence cadence, coverage and "
        "de-risking velocities, and the projected horizon."
    )
    lines.append("")

    if metadata:
        generated = _text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    _md_section(lines, "Counts", _COUNT_KEYS, counts)
    _md_section(lines, "Velocity", _VELOCITY_KEYS, velocity)
    _md_section(lines, "Forecast", _FORECAST_KEYS, forecast)

    if insights:
        lines.append("## Insights")
        lines.append("")
        for text in insights:
            lines.append(f"- {_escape_md_cell(text)}")
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Validation momentum"]
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
    "validation_momentum_to_csv",
    "validation_momentum_to_json",
    "validation_momentum_to_markdown",
]

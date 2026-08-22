"""CSV, JSON, and Markdown exports for the stress-scenario resilience payload.

``GET /simulations/{id}/stress-scenarios`` answers *how fragile is this
business under macroeconomic and market stress?*; these exports put that
answer in a founder's spreadsheet, data pipeline, or board update.
Formatting is pure and reuses the exact response payload produced by the
analyzer's ``to_dict`` — no recomputation happens here.

CSV is a multi-section document: metadata header, a resilience summary,
and one row per stress scenario with its projected conversion, delta,
vulnerability score, risk level, impact summary, and recommended
mitigation. Cells are guarded against spreadsheet formula injection.
JSON is an envelope with stable metadata and the unmodified payload.
Markdown is a founder-facing brief with the headline resilience numbers
and one row per scenario.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_SUMMARY_KEYS: tuple[str, ...] = (
    "simulation_id",
    "base_conversion_rate",
    "overall_resilience_score",
    "most_vulnerable_scenario",
    "most_resilient_scenario",
    "scenario_count",
)

_IMPACT_HEADERS: tuple[str, ...] = (
    "scenario_key",
    "scenario_name",
    "description",
    "projected_conversion_rate",
    "conversion_delta_pct",
    "vulnerability_score",
    "risk_level",
    "impact_summary",
    "mitigation_recommendation",
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


def _csv_cell(value: Any) -> object:
    """Blank non-finite numbers, guard formula-leading strings."""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped[:1] in ("=", "+", "-", "@") or value[:1] in (
            "\t",
            "\r",
            "\n",
        ):
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    writer.writerow([_csv_cell(value) for value in row])


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
            "simulation_id",
            "project_id",
            "format_version",
        )
    ]


def _impact_cell(value: Any) -> object:
    """Keep real numbers native in CSV; guard everything else as text.

    Passing floats through unconverted means ``-0.25`` lands in the
    spreadsheet as a number instead of the apostrophe-escaped text the
    formula guard produces for string inputs.
    """
    if isinstance(value, bool):
        return _text(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return value
    return _csv_cell(_text(value))


def _summary_section(data: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers plus a derived scenario count."""
    section: dict[str, Any] = {}
    for key in _SUMMARY_KEYS:
        if key == "scenario_count":
            continue
        section[key] = data.get(key)
    section["scenario_count"] = len(data.get("scenario_impacts") or [])
    return section


def stress_scenarios_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a stress-scenario payload as a multi-section CSV."""
    data = _as_dict(payload)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Resilience Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_section(data).items():
        _write_row(writer, [key, _text(_csv_cell(value))])
    _write_row(writer, [])

    _write_row(writer, ["section", "Scenario Impacts"])
    _write_row(writer, list(_IMPACT_HEADERS))
    for impact in data.get("scenario_impacts") or []:
        row = _as_dict(impact)
        _write_row(
            writer,
            [_impact_cell(row.get(key)) for key in _IMPACT_HEADERS],
        )
    _write_row(writer, [])

    meta = _as_dict(data.get("meta"))
    if meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _text(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def stress_scenarios_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a stress-scenario payload as a strict JSON envelope."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "stress_scenarios": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    """Escape pipes/newlines so cells can't break Markdown tables."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_cell(value: Any) -> str:
    """Generic Markdown cell renderer for scalar values."""
    if value is None:
        return "—"
    if isinstance(value, float) and not math.isfinite(value):
        return "—"
    return _escape_md_cell(str(value))


def _md_pct(value: Any) -> str:
    """Format a fraction as a percentage, or return a dash."""
    if value is None:
        return "—"
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return _escape_md_cell(value)
    if not math.isfinite(fraction):
        return "—"
    return f"{fraction * 100:.1f}%"


def _md_date(value: Any) -> str:
    """Render a timestamp as a founder-friendly date in the brief."""
    if value is None or value == "":
        return "—"
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except (TypeError, ValueError):
            pass
    text = str(value)
    return _escape_md_cell(text.split("T", 1)[0].split(" ", 1)[0])


def stress_scenarios_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a stress-scenario payload as a founder-facing brief."""
    data = _as_dict(payload)
    impacts = data.get("scenario_impacts") or []

    lines: list[str] = []
    lines.append("# Stress Scenarios")
    lines.append("")
    lines.append(
        "How the simulated funnel holds up under recession, price-war, "
        "viral-catalyst, and channel-bottleneck conditions."
    )
    lines.append("")

    if metadata and metadata.get("generated_at"):
        lines.append(f"*Generated: {_md_date(metadata['generated_at'])}*")
        lines.append("")

    lines.append("## Resilience")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    summary_labels = (
        ("base_conversion_rate", "Base conversion rate"),
        ("overall_resilience_score", "Resilience score (/100)"),
        ("most_vulnerable_scenario", "Most vulnerable scenario"),
        ("most_resilient_scenario", "Most resilient scenario"),
        ("scenario_count", "Scenarios evaluated"),
    )
    for key, label in summary_labels:
        value = (
            len(impacts)
            if key == "scenario_count"
            else data.get(key)
        )
        lines.append(f"| {label} | {_md_cell(value)} |")
    lines.append("")

    lines.append("## Scenario Impacts")
    lines.append("")
    if not impacts:
        lines.append("_No scenarios returned._")
    else:
        lines.append(
            "| Scenario | Risk | Projected CR | Δ% | Vulnerability | Mitigation |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for raw in impacts:
            impact = _as_dict(raw)
            cells = [
                _escape_md_cell(impact.get("scenario_name") or impact.get("scenario_key")),
                _escape_md_cell(impact.get("risk_level")),
                _md_cell(impact.get("projected_conversion_rate")),
                _md_pct(impact.get("conversion_delta_pct")),
                _md_pct(impact.get("vulnerability_score")),
                _escape_md_cell(impact.get("mitigation_recommendation")),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("---")
    lines.append("")
    footer = ["Stress scenarios"]
    simulation_id = _text(data.get("simulation_id"))
    if not simulation_id and metadata:
        simulation_id = _text(metadata.get("simulation_id"))
    if simulation_id:
        footer.append(f"Simulation {simulation_id}")
    if metadata and metadata.get("generated_at"):
        footer.append(f"Generated {_md_date(metadata['generated_at'])}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "stress_scenarios_to_csv",
    "stress_scenarios_to_json",
    "stress_scenarios_to_markdown",
]

"""CSV/JSON/Markdown export helpers for the batch what-if scenario comparison.

The route layer in ``app/api/v1/simulations.py`` builds a
:class:`app.schemas.what_if_batch.WhatIfBatchOut` payload; this module renders
that payload as a spreadsheet-friendly CSV, an indented JSON document, or a
founder-facing Markdown brief so founders can bring the ranked scenario
comparison into their planning tools or share it with a team.

The CSV follows the same lightweight multi-section convention as the
unit-economics and founder-action-plan exports: an optional metadata block, a
summary section, one row per ranked scenario, best/worst scenario details, and
an optional meta key/value section. Missing optional fields render as blanks
rather than crashing the export.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.schemas.what_if import WhatIfOut


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _value(value: Any) -> object:
    return "" if value is None else value


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _markdown_cell(value: object) -> str:
    """Escape a value for use inside a Markdown table cell.

    Pipe characters become ``\\|`` so table structure is preserved (this also
    covers the pipe separators used in direction/category summaries), and
    line breaks collapse to a single space so the row stays on one line.
    """
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "simulation_id",
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _direction_breakdown_text(mapping: object) -> str:
    """Render a direction-count dict as ``UP:2|DOWN:1|FLAT:0``."""
    if not isinstance(mapping, dict):
        return ""
    return "|".join(
        f"{key}:{int(value)}"
        for key, value in sorted(mapping.items(), key=lambda kv: (-int(kv[1]), str(kv[0])))
    )


def _top_categories_text(rows: object) -> str:
    """Render the top-category list as ``category:count|category:count``."""
    if not isinstance(rows, list):
        return ""
    rendered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("category") or "")
        count = str(int(row.get("count") or 0))
        if name:
            rendered.append(f"{name}:{count}")
    return "|".join(rendered)


def _summary_section_rows(summary: Any) -> list[list[object]]:
    """Render the WhatIfSummary payload as key/value rows."""
    data = _as_dict(summary)
    rows: list[list[object]] = []
    summary_keys = (
        "scenario_count",
        "avg_delta",
        "best_delta",
        "worst_delta",
        "direction_breakdown",
        "top_categories",
    )
    for key in summary_keys:
        value = data.get(key)
        if key == "direction_breakdown":
            value = _direction_breakdown_text(value)
        elif key == "top_categories":
            value = _top_categories_text(value)
        rows.append([key, _value(value)])
    return rows


def _scenario_header() -> list[str]:
    """Return the CSV header for the ranked-scenario section."""
    return ["rank", "label", *WhatIfOut.to_csv_header()]


def _matched_categories_text(categories: object, separator: str = "|") -> str:
    """Render the matched-keyword list as a delimited string."""
    if not isinstance(categories, list):
        return "" if not categories else str(categories)
    return separator.join(str(item) for item in categories)


def _scenario_row(ranked: Any) -> list[object]:
    """Render one ``WhatIfBatchScenarioOut`` as a CSV row."""
    data = _as_dict(ranked)
    scenario = data.get("scenario") or {}
    rank = data.get("rank", "")
    label = data.get("label", "")
    if hasattr(ranked, "scenario") and hasattr(ranked.scenario, "to_csv_row"):
        scenario_row = ranked.scenario.to_csv_row()
    elif isinstance(scenario, dict):
        scenario_row = [
            str(scenario.get("simulation_id", "")),
            str(scenario.get("project_id", "")),
            scenario.get("base_conversion_rate", ""),
            scenario.get("projected_conversion_rate", ""),
            scenario.get("conversion_delta", ""),
            scenario.get("conversion_delta_pct", ""),
            (scenario.get("meta") or {}).get("dominant_direction", ""),
            (scenario.get("meta") or {}).get("sensitivity_label", ""),
            _matched_categories_text(
                (scenario.get("meta") or {}).get("matched_keyword_categories")
            ),
        ]
    else:
        scenario_row = []
    return [rank, label, *scenario_row]


def _scenario_details_rows(scenario_block: Any) -> list[list[object]]:
    """Render best/worst scenario blocks as key/value rows."""
    if scenario_block is None:
        return []
    data = _as_dict(scenario_block)
    scenario = data.get("scenario") or {}
    rows: list[list[object]] = []
    for key in ("rank", "label", "simulation_id", "project_id"):
        value = scenario.get(key) if key in ("simulation_id", "project_id") else data.get(key)
        rows.append([key, _value(value)])
    rows.append(["base_conversion_rate", _value(scenario.get("base_conversion_rate"))])
    rows.append(["projected_conversion_rate", _value(scenario.get("projected_conversion_rate"))])
    rows.append(["conversion_delta_pct", _value(scenario.get("conversion_delta_pct"))])
    rows.append(["direction", _value((scenario.get("meta") or {}).get("dominant_direction"))])
    rows.append(["sensitivity", _value((scenario.get("meta") or {}).get("sensitivity_label"))])
    return rows


def what_if_batch_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a batch what-if payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "What-If Batch Summary"])
    _write_row(writer, ["key", "value"])
    _write_row(writer, ["simulation_id", _value(data.get("simulation_id"))])
    _write_row(writer, ["project_id", _value(data.get("project_id"))])
    _write_row(writer, ["status", _value(data.get("status"))])
    for row in _summary_section_rows(data.get("summary") or {}):
        _write_row(writer, row)
    _write_row(writer, [])

    # Ranked scenarios.
    _write_row(writer, ["section", "Ranked Scenarios"])
    _write_row(writer, _scenario_header())
    for raw in data.get("scenarios") or []:
        _write_row(writer, _scenario_row(raw))
    _write_row(writer, [])

    # Best / worst scenario blocks.
    for name, key in (("Best Scenario", "best_scenario"), ("Worst Scenario", "worst_scenario")):
        block = data.get(key)
        if block is None:
            continue
        _write_row(writer, ["section", name])
        _write_row(writer, ["key", "value"])
        for row in _scenario_details_rows(block):
            _write_row(writer, row)
        _write_row(writer, [])

    # Meta key/value section.
    meta = _as_dict(data.get("meta") or {})
    if meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            _write_row(writer, [key, _value(meta[key])])
        _write_row(writer, [])

    return buffer.getvalue()


def what_if_batch_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a batch what-if payload as an indented JSON document."""
    return json.dumps(
        {"metadata": metadata or {}, "what_if_batch": _as_dict(payload)},
        default=str,
        indent=2,
    )


def _summary_markdown_rows(summary: Any) -> list[tuple[str, str]]:
    data = _as_dict(summary)
    return [
        ("Scenario count", str(data.get("scenario_count", ""))),
        ("Average delta", str(data.get("avg_delta", ""))),
        ("Best delta", str(data.get("best_delta", ""))),
        ("Worst delta", str(data.get("worst_delta", ""))),
        ("Direction breakdown", _direction_breakdown_text(data.get("direction_breakdown"))),
        ("Top categories", _top_categories_text(data.get("top_categories"))),
    ]


def _scenario_markdown_row(ranked: Any) -> list[object]:
    data = _as_dict(ranked)
    scenario = data.get("scenario") or {}
    meta = scenario.get("meta") or {}
    categories_text = _matched_categories_text(
        meta.get("matched_keyword_categories"), separator=", "
    )
    return [
        data.get("rank", ""),
        data.get("label", ""),
        scenario.get("base_conversion_rate", ""),
        scenario.get("projected_conversion_rate", ""),
        scenario.get("conversion_delta_pct", ""),
        meta.get("dominant_direction", ""),
        meta.get("sensitivity_label", ""),
        categories_text,
    ]


def what_if_batch_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a batch what-if payload as a founder-facing Markdown brief."""
    data = _as_dict(payload)
    lines: list[str] = []
    lines.append(f"# What-If Batch — Simulation {data.get('simulation_id', '')}")
    lines.append("")
    lines.append(
        f"Project {data.get('project_id', '')} · status `{data.get('status', '')}`"
    )
    if metadata:
        lines.append(f"Exported {metadata.get('generated_at', '')}")
    lines.append("")

    summary = _as_dict(data.get("summary") or {})
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for key, value in _summary_markdown_rows(summary):
        lines.append(f"| {_markdown_cell(key)} | {_markdown_cell(value)} |")
    lines.append("")

    scenarios = data.get("scenarios") or []
    lines.append("## Ranked Scenarios")
    lines.append("")
    if not scenarios:
        lines.append("_No scenarios returned._")
    else:
        lines.append("| Rank | Label | Base CR | Projected CR | Δ% | Direction | Sensitivity | Matched categories |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for ranked in scenarios:
            cells = [_markdown_cell(cell) for cell in _scenario_markdown_row(ranked)]
            lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    lines.append("")

    for name, key in (("Best Scenario", "best_scenario"), ("Worst Scenario", "worst_scenario")):
        block = data.get(key)
        if block is None:
            continue
        block_data = _as_dict(block)
        scenario = _as_dict(block_data.get("scenario") or {})
        meta = _as_dict(scenario.get("meta") or {})
        lines.append(f"## {name}")
        lines.append("")
        lines.append(f"- Rank: {_markdown_cell(block_data.get('rank', ''))}")
        lines.append(f"- Label: {_markdown_cell(block_data.get('label', ''))}")
        lines.append(
            f"- Projected conversion: "
            f"{_markdown_cell(scenario.get('projected_conversion_rate', ''))}"
        )
        lines.append(
            f"- Delta %: {_markdown_cell(scenario.get('conversion_delta_pct', ''))}"
        )
        lines.append(
            f"- Direction: {_markdown_cell(meta.get('dominant_direction', ''))}"
        )
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "what_if_batch_to_csv",
    "what_if_batch_to_json",
    "what_if_batch_to_markdown",
]

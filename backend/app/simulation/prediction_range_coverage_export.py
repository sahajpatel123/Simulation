"""CSV / JSON / Markdown export helpers for the prediction-range coverage digest.

The prediction-range coverage endpoint
(``GET /projects/{id}/prediction-range-coverage``) tells a founder how often
the accuracy-adjusted conversion band has historically contained reality.
This module renders that same digest for download:

* CSV — a multi-section spreadsheet (metadata, summary, key signals, and one
  row per out-of-sample band check) so founders can keep a calibration
  track-record in Sheets or Excel;
* JSON — a strict, machine-readable envelope for BI pipelines and tools;
* Markdown — a concise founder-facing brief for docs, Notion, or investor
  updates.

The module stays pure and defensive: malformed rows, non-finite numbers,
missing fields, and empty payloads degrade to safe defaults instead of
raising, and CSV cells are guarded against spreadsheet formula injection.
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
    "generated_at",
    "total_project_outcomes",
    "evaluated_runs",
    "within_range_count",
    "coverage_rate",
    "mean_margin",
    "worst_miss",
    "verdict",
    "narrative",
)

_ROW_HEADERS: list[str] = [
    "simulation_id",
    "project_id",
    "predicted_conversion_rate",
    "actual_conversion_rate",
    "low",
    "high",
    "history_count",
    "calibration_source",
    "confidence_label",
    "within",
    "margin",
    "evaluated",
    "created_at",
]


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Coerce a value to a finite float, or ``default`` when unusable."""
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_rate(value: Any) -> float | None:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(max(0.0, min(1.0, parsed)), 6)


def _json_safe(value: Any) -> Any:
    """Recursively coerce a JSON-like value for strict JSON serialization.

    Non-finite floats (``NaN``/``±Infinity``) are not valid JSON tokens and
    cannot be persisted by PostgreSQL jsonb; render them as ``null`` instead
    of emitting tokens that strict BI parsers reject.
    """
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_text(value: Any) -> str:
    """Render a nested value as compact, deterministic JSON text."""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(
                _json_safe(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            return _safe_text(value)
    return _safe_text(value)


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with a formula character are quoted, and cells that
    embed ``=`` inside a prefix (e.g. ``A:=HYPERLINK(...)``) are quoted too
    so the whole cell can never be interpreted as an executable formula by
    Excel.
    """
    if isinstance(value, str):
        stripped = value.lstrip()
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") or (
            stripped[:1] in ("=", "+", "-", "@", "\t", "\r")
            and stripped != value
        ) or "=" in value:
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
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
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _summary_rows(data: dict[str, Any]) -> list[tuple[str, object]]:
    """Render the coverage summary as deterministic key/value rows."""
    rows: list[tuple[str, object]] = []
    for key in _SUMMARY_KEYS:
        value = data.get(key)
        if key in {"coverage_rate", "mean_margin"}:
            rows.append((key, "" if value is None else _safe_float(value)))
        elif key == "worst_miss":
            rows.append((key, _json_text(value) if value else ""))
        else:
            rows.append((key, "" if value is None else value))
    return rows


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in data.get("rows") or [] if isinstance(row, dict)
    ]


def _key_signals(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        signal
        for signal in data.get("key_signals") or []
        if isinstance(signal, dict)
    ]


def _csv_rate(value: Any) -> object:
    """Render a conversion-rate cell as a float, or blank when missing."""
    parsed = _bounded_rate(value)
    return "" if parsed is None else parsed


def _row_values(row: dict[str, Any]) -> list[object]:
    """Render one band-check row as CSV-safe scalar values."""
    within = row.get("within")
    simulation_id = row.get("simulation_id")
    return [
        _safe_int(simulation_id) if simulation_id is not None else "",
        _safe_int(row.get("project_id")),
        _csv_rate(row.get("predicted_conversion_rate")),
        _csv_rate(row.get("actual_conversion_rate")),
        _csv_rate(row.get("low")),
        _csv_rate(row.get("high")),
        _safe_int(row.get("history_count")),
        _safe_text(row.get("calibration_source")),
        _safe_text(row.get("confidence_label")),
        "yes" if within is True else ("no" if within is False else ""),
        "" if row.get("margin") is None else _safe_float(row.get("margin")),
        "yes" if row.get("evaluated") else "no",
        _safe_text(row.get("created_at")),
    ]


def prediction_range_coverage_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a prediction-range coverage payload as a multi-section CSV."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    _write_row(writer, ["section", "Prediction Range Coverage Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_rows(data):
        _write_row(writer, [key, value])
    _write_row(writer, [])

    signals = _key_signals(data)
    _write_row(writer, ["section", "Key Signals"])
    _write_row(writer, ["label", "value", "severity", "display"])
    for signal in signals:
        _write_row(
            writer,
            [
                _safe_text(signal.get("label")),
                "" if signal.get("value") is None else signal.get("value"),
                _safe_text(signal.get("severity")),
                _safe_text(signal.get("display")),
            ],
        )
    _write_row(writer, [])

    _write_row(writer, ["section", "Out-of-Sample Band Checks"])
    _write_row(writer, _ROW_HEADERS)
    for row in _rows(data):
        _write_row(writer, _row_values(row))

    return buffer.getvalue()


def prediction_range_coverage_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a prediction-range coverage payload as a strict JSON document."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "prediction_range_coverage": _json_safe(_as_dict(payload)),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _escape_md_cell(value: Any) -> str:
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    parsed = _bounded_rate(value)
    if parsed is None:
        return "—"
    return f"{parsed:.2%}"


def _md_float(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "—"
    return f"{parsed:.4f}"


def prediction_range_coverage_to_markdown(
    payload: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a prediction-range coverage payload as a founder-facing brief."""
    data = _as_dict(payload)
    lines: list[str] = []
    lines.append("# Prediction Range Coverage")
    lines.append("")
    lines.append(
        "How often the accuracy-adjusted conversion band has contained "
        "recorded outcomes, evaluated strictly out-of-sample."
    )
    lines.append("")
    if metadata:
        generated = _safe_text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Verdict")
    lines.append("")
    verdict = _escape_md_cell(data.get("verdict")) or "INSUFFICIENT_DATA"
    narrative = _safe_text(data.get("narrative"))
    lines.append(f"**{verdict}**")
    if narrative:
        lines.append("")
        lines.append(_escape_md_cell(narrative))
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    summary_pairs = [
        ("Project", _safe_int(data.get("project_id"))),
        ("Total project outcomes", _safe_int(data.get("total_project_outcomes"))),
        ("Evaluated out-of-sample runs", _safe_int(data.get("evaluated_runs"))),
        ("Within range", _safe_int(data.get("within_range_count"))),
        ("Coverage rate", _md_pct(data.get("coverage_rate"))),
        ("Mean miss margin", _md_float(data.get("mean_margin"))),
    ]
    for label, value in summary_pairs:
        lines.append(f"| {label} | {_escape_md_cell(value)} |")
    worst_miss = data.get("worst_miss")
    if isinstance(worst_miss, dict) and worst_miss:
        sim_id = _safe_int(worst_miss.get("simulation_id"))
        margin = _md_float(worst_miss.get("margin"))
        lines.append(
            "| Worst miss | "
            f"Simulation {sim_id or '?'} (margin {margin}) |"
        )
    lines.append("")

    rows = _rows(data)
    lines.append("## Out-of-Sample Band Checks")
    lines.append("")
    lines.append(
        "| Simulation | Predicted | Actual | Band | Within | Margin | "
        "History | Source |"
    )
    lines.append("| --- | ---: | ---: | --- | --- | ---: | ---: | --- |")
    for row in rows:
        low = _md_pct(row.get("low"))
        high = _md_pct(row.get("high"))
        within = row.get("within")
        within_text = "yes" if within is True else (
            "no" if within is False else "—"
        )
        lines.append(
            "| {sim} | {predicted} | {actual} | {low} – {high} | "
            "{within} | {margin} | {history} | {source} |".format(
                sim=_safe_int(row.get("simulation_id")) or "—",
                predicted=_md_pct(row.get("predicted_conversion_rate")),
                actual=_md_pct(row.get("actual_conversion_rate")),
                low=low,
                high=high,
                within=within_text,
                margin=_md_float(row.get("margin")),
                history=_safe_int(row.get("history_count")),
                source=_escape_md_cell(row.get("calibration_source"))
                or "—",
            )
        )
    lines.append("")

    signals = _key_signals(data)
    if signals:
        lines.append("## Key Signals")
        lines.append("")
        for signal in signals:
            display = _safe_text(signal.get("display"))
            if not display:
                display = _safe_text(signal.get("label"))
            lines.append(
                f"- **{_escape_md_cell(signal.get('label'))}** — "
                f"{_escape_md_cell(display)}"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    footer = [f"Project {_safe_int(data.get('project_id'))}"]
    if data.get("generated_at"):
        footer.append(
            f"Generated {_escape_md_cell(data.get('generated_at'))}"
        )
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "prediction_range_coverage_to_csv",
    "prediction_range_coverage_to_json",
    "prediction_range_coverage_to_markdown",
]

"""CSV, JSON, and Markdown exports for the run-vs-run comparison payload.

``GET /simulations/{id}/compare/{baseline_id}`` answers *did the re-run
move the projection?*; these exports put that answer in a founder's
spreadsheet, data pipeline, or investor update. Formatting is pure and
reuses the exact response payload produced by ``build_simulation_comparison``
— no recomputation happens here.

CSV is a multi-section document: metadata header, the headline numbers,
one row per funnel-stage drop-off change, one row per cluster mover, and
the narrative. Real numbers stay native so negative deltas land as
numbers; string cells are guarded against spreadsheet formula injection.
JSON is an envelope with stable metadata and the unmodified payload.
Markdown is a founder-facing brief with the verdict callout, stage
deltas, and cluster movers.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_HEADLINE_KEYS: tuple[str, ...] = (
    "conversion_before",
    "conversion_after",
    "conversion_delta_pp",
    "conversion_delta_pct",
    "verdict",
    "revenue_before",
    "revenue_after",
    "confidence_before",
    "confidence_after",
    "signal_quality_before",
    "signal_quality_after",
    "worst_drop_off_stage_before",
    "worst_drop_off_stage_after",
    "worst_stage_changed",
)

_STAGE_HEADERS: tuple[str, ...] = (
    "state",
    "drop_off_before",
    "drop_off_after",
    "drop_off_delta_pp",
)

_CLUSTER_HEADERS: tuple[str, ...] = (
    "cluster_id",
    "conversion_before",
    "conversion_after",
    "conversion_delta_pp",
    "direction",
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


def _num_cell(value: Any) -> object:
    """Keep real numbers native in CSV; guard everything else as text."""
    if isinstance(value, bool):
        return _text(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return value
    return _csv_cell(_text(value))


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


def _escape_md_cell(value: Any) -> str:
    """Escape pipes and newlines so a cell cannot break a Markdown table."""
    return _text(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    """Render a fraction as a percentage cell (None-safe)."""
    number = value if isinstance(value, (int, float)) else None
    if number is None:
        return "—"
    return f"{float(number):.2%}"


def _md_num(value: Any, suffix: str = "") -> str:
    """Render a numeric cell with a dash fallback for missing values."""
    if value is None:
        return "—"
    if isinstance(value, float):
        text = f"{value:+.2f}" if suffix == "pp" else f"{value:.4f}"
    else:
        text = _text(value)
    return f"{text}{suffix}"


def simulation_compare_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a run-comparison payload as a multi-section CSV."""
    data = _as_dict(payload)
    headline = _as_dict(data.get("headline"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    for row in _metadata_rows(metadata):
        writer.writerow(row)

    writer.writerow([])
    writer.writerow(["Headline"])
    writer.writerow(["metric", "value"])
    for key in _HEADLINE_KEYS:
        writer.writerow([key, _num_cell(headline.get(key))])

    writer.writerow([])
    writer.writerow(["Stage Deltas"])
    writer.writerow(list(_STAGE_HEADERS))
    for raw in data.get("stage_deltas") or []:
        row = _as_dict(raw)
        writer.writerow(
            [_num_cell(row.get(key)) for key in _STAGE_HEADERS]
        )

    writer.writerow([])
    writer.writerow(["Cluster Movers"])
    writer.writerow(list(_CLUSTER_HEADERS))
    for raw in data.get("cluster_deltas") or []:
        row = _as_dict(raw)
        writer.writerow(
            [_num_cell(row.get(key)) for key in _CLUSTER_HEADERS]
        )

    writer.writerow([])
    writer.writerow(["Narrative", _csv_cell(data.get("narrative"))])
    writer.writerow(["format_version", FORMAT_VERSION])

    return buffer.getvalue()


def simulation_compare_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a run-comparison payload as a stable JSON envelope."""
    envelope = {
        "metadata": dict(metadata or {}),
        "simulation_comparison": _json_safe(_as_dict(payload)),
    }
    return (
        json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
            indent=2,
        )
        + "\n"
    )


def _stage_rows_md(data: dict[str, Any]) -> list[str]:
    lines = [
        "| State | Drop-off before | Drop-off after | Δ (pp) |",
        "| --- | --- | --- | --- |",
    ]
    rows = data.get("stage_deltas") or []
    if not rows:
        lines.append("| _No stage data._ | | | |")
        return lines
    for raw in rows:
        row = _as_dict(raw)
        lines.append(
            "| {} | {} | {} | {} |".format(
                _escape_md_cell(row.get("state")),
                _md_pct(row.get("drop_off_before")),
                _md_pct(row.get("drop_off_after")),
                _md_num(row.get("drop_off_delta_pp"), suffix="pp"),
            )
        )
    return lines


def _cluster_rows_md(data: dict[str, Any]) -> list[str]:
    lines = [
        "| Cluster | Before | After | Δ (pp) | Direction |",
        "| --- | --- | --- | --- | --- |",
    ]
    rows = data.get("cluster_deltas") or []
    if not rows:
        lines.append("| _No cluster movers returned._ | | | | |")
        return lines
    for raw in rows:
        row = _as_dict(raw)
        lines.append(
            "| {} | {} | {} | {} | {} |".format(
                _escape_md_cell(row.get("cluster_id")),
                _md_pct(row.get("conversion_before")),
                _md_pct(row.get("conversion_after")),
                _md_num(row.get("conversion_delta_pp"), suffix="pp"),
                _escape_md_cell(row.get("direction")),
            )
        )
    return lines


def simulation_compare_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a founder-facing Markdown brief of the run comparison."""
    data = _as_dict(payload)
    headline = _as_dict(data.get("headline"))
    meta = metadata or {}

    sim_id = meta.get("comparison_simulation_id") or data.get("simulation_id")
    baseline_id = meta.get("comparison_baseline_id") or data.get("baseline_id")

    lines = [
        f"# Run Comparison — Simulation {sim_id} vs {baseline_id}",
        "",
    ]

    verdict = _text(headline.get("verdict")) or "FLAT"
    delta_pp = headline.get("conversion_delta_pp")
    sign = "+" if isinstance(delta_pp, (int, float)) and delta_pp >= 0 else ""
    lines.append(
        "**Verdict: {}** — predicted conversion {} → {} ({}{}pp)".format(
            verdict,
            _md_pct(headline.get("conversion_before")),
            _md_pct(headline.get("conversion_after")),
            sign,
            _text(delta_pp),
        )
    )
    lines.append("")

    narrative = _text(data.get("narrative"))
    if narrative:
        lines.append(f"> {narrative}")
        lines.append("")

    lines.append("## Stage Deltas")
    lines.extend(_stage_rows_md(data))
    lines.append("")
    lines.append("## Cluster Movers")
    lines.extend(_cluster_rows_md(data))

    lines.append("")
    generated = _text(meta.get("generated_at"))
    date_part = generated.split("T")[0] if generated else ""
    lines.append(
        f"*Run comparison · Simulation {sim_id} vs {baseline_id}"
        + (f" · Generated {date_part}" if date_part else "")
        + "*"
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "FORMAT_VERSION",
    "simulation_compare_to_csv",
    "simulation_compare_to_json",
    "simulation_compare_to_markdown",
]

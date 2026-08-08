"""CSV / JSON / Markdown export helpers for the simulation-comparison read.

The simulation-comparison endpoint
(``POST /api/v1/simulations/compare``) returns a structured A/B winner,
per-cluster conversion table, and cross-simulation domain-finding consensus.
This module renders the same deterministic payload for download:

* CSV — a multi-section spreadsheet (summary, simulation refs,
  per-cluster conversion + delta table, domain-finding comparison) so
  founders can keep a record in Sheets/Excel.
* JSON — a machine-readable envelope for tools and integrations.
* Markdown — a concise founder-facing brief for docs, Notion, or an
  investor update.

The module stays pure and defensive: missing fields, malformed rows, and
empty sections degrade to safe defaults without raising.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _as_dict_map(value: Any) -> dict[Any, Any]:
    return value if isinstance(value, dict) else {}


def _lookup(value: Any, key: Any) -> Any:
    """Look up a dict value tolerating int/str key mismatches.

    Comparison payloads can arrive either as a Pydantic model (Python-mode
    ``model_dump`` keeps ``dict[int, ...]`` keys as ints) or as a JSON-style
    dict (where those same keys are strings).  This helper makes the export
    serializers indifferent to that difference.
    """
    if not isinstance(value, dict):
        return None
    if key in value:
        return value[key]
    if isinstance(key, int):
        return value.get(str(key))
    try:
        int_key = int(key)
    except (TypeError, ValueError):
        return None
    return value.get(int_key)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    A cell is neutralised when it begins with a formula character or when
    it embeds ``=`` inside a prefix such as ``A:=HYPERLINK(...)`` so the
    whole cell can never be interpreted as an executable formula by Excel.
    """
    if isinstance(value, str):
        if value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return f"'{value}"
        if "=" in value:
            return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    writer.writerow([_safe_csv_cell(value) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "project_id",
        "comparison_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _simulation_ids(data: dict[str, Any]) -> list[int]:
    """Ordered simulation ids from the top-level simulations list."""
    sims = _as_list(data.get("simulations"))
    ids: list[int] = []
    for sim in sims:
        if isinstance(sim, dict):
            ids.append(_safe_int(sim.get("simulation_id")))
    return ids


def _summary_dict(data: dict[str, Any]) -> dict[str, Any]:
    summary = data.get("summary")
    if isinstance(summary, dict):
        return summary
    return {}


def _id_label(data: dict[str, Any], sim_id: Any) -> str:
    sims = _as_list(data.get("simulations"))
    for idx, sim in enumerate(sims, start=1):
        if not isinstance(sim, dict):
            continue
        if _safe_int(sim.get("simulation_id")) == _safe_int(sim_id):
            return chr(ord("A") + idx - 1) if idx <= 26 else f"Sim {_safe_int(sim_id)}"
    return f"Sim {_safe_int(sim_id)}"


def _findings_text(findings: Any) -> str:
    parts: list[str] = []
    for finding in _as_list(findings):
        if not isinstance(finding, dict):
            continue
        text = _safe_text(finding.get("finding") or finding.get("title"))
        if text:
            parts.append(text)
    return " | ".join(parts)


def simulation_comparison_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a simulation-comparison payload as a multi-section CSV string."""
    data = _as_dict(payload)
    sim_ids = _simulation_ids(data)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Simulation Comparison Summary"])
    _write_row(writer, ["key", "value"])
    summary = _summary_dict(data)
    for key in (
        "best_simulation_id",
        "best_conversion_rate",
        "worst_simulation_id",
        "worst_conversion_rate",
        "conversion_spread_pct",
        "revenue_spread_pct",
        "winner_label",
        "verdict",
    ):
        value = summary.get(key)
        if key in {"best_simulation_id", "worst_simulation_id"} and isinstance(
            value, int
        ):
            _write_row(writer, [key, f"{value} ({_id_label(data, value)})"])
        else:
            _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, ["project_id", _safe_text(data.get("project_id"))])
    _write_row(writer, ["comparison_id", _safe_text(data.get("comparison_id"))])
    _write_row(writer, ["generated_at", _safe_text(data.get("generated_at"))])
    _write_row(writer, [])

    # Simulation references.
    _write_row(writer, ["section", "Simulations Compared"])
    _write_row(
        writer,
        [
            "label",
            "simulation_id",
            "status",
            "conversion_rate",
            "revenue_projection",
            "signal_quality",
            "product_type_detected",
            "created_at",
        ],
    )
    for idx, sim in enumerate(_as_list(data.get("simulations")), start=1):
        if not isinstance(sim, dict):
            continue
        _write_row(
            writer,
            [
                chr(ord("A") + idx - 1) if idx <= 26 else f"Sim {idx}",
                _safe_int(sim.get("simulation_id")),
                _safe_text(sim.get("status")),
                _safe_float(sim.get("conversion_rate")),
                _safe_float(sim.get("revenue_projection"), 0.0),
                _safe_float(sim.get("signal_quality"), 0.0),
                _safe_text(sim.get("product_type_detected")),
                _safe_text(sim.get("created_at")),
            ],
        )
    _write_row(writer, [])

    # Cluster conversion + delta table.
    _write_row(writer, ["section", "Cluster Conversion Comparison"])
    _write_row(
        writer,
        ["cluster_id", "cluster_name", "population_weight", "best_simulation_id", "winner"]
        + [f"conversion_{sid}" for sid in sim_ids]
        + [f"delta_from_best_{sid}" for sid in sim_ids],
    )
    for row in _as_list(data.get("cluster_comparison")):
        if not isinstance(row, dict):
            continue
        conversions = _as_dict_map(row.get("conversions"))
        deltas = _as_dict_map(row.get("delta_from_best"))
        _write_row(
            writer,
            [
                _safe_text(row.get("cluster_id")),
                _safe_text(row.get("cluster_name")),
                _safe_float(row.get("population_weight")),
                _safe_int(row.get("best_simulation_id")),
                _safe_text(row.get("winner_label")),
            ]
            + [_safe_float(_lookup(conversions, sid)) for sid in sim_ids]
            + [_safe_float(_lookup(deltas, sid)) for sid in sim_ids],
        )
    _write_row(writer, [])

    # Domain findings.
    _write_row(writer, ["section", "Domain Finding Comparison"])
    _write_row(
        writer,
        ["domain", "consensus", "recommendation", "severities", "findings"],
    )
    for row in _as_list(data.get("domain_finding_comparison")):
        if not isinstance(row, dict):
            continue
        severities: list[str] = []
        finding_texts: list[str] = []
        for sid in sim_ids:
            severity = _safe_text(
                _lookup(row.get("severity_by_sim"), sid)
            )
            severities.append(
                f"{_id_label(data, sid)}:{severity}" if severity else f"{_id_label(data, sid)}:"
            )
            finding_texts.append(
                f"{_id_label(data, sid)}:"
                f"{_findings_text(_lookup(row.get('findings'), sid))}"
            )
        _write_row(
            writer,
            [
                _safe_text(row.get("domain")),
                _safe_text(row.get("consensus")),
                _safe_text(row.get("recommendation")),
                " | ".join(severities),
                " | ".join(finding_texts),
            ],
        )
    _write_row(writer, [])

    # Metadata section.
    meta = _as_dict_map(data.get("metadata"))
    if meta:
        _write_row(writer, ["section", "Meta"])
        _write_row(writer, ["key", "value"])
        for key in sorted(meta):
            value = meta[key]
            if isinstance(value, (dict, list)):
                _write_row(writer, [key, json.dumps(value, default=str)])
            else:
                _write_row(writer, [key, _safe_text(value)])

    return buffer.getvalue()


def simulation_comparison_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a simulation-comparison payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "simulation_comparison": _as_dict(payload),
        },
        default=str,
        indent=2,
    )


def _escape_md_cell(value: Any) -> str:
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _pct(value: Any, *, plus: bool = False) -> str:
    parsed = _safe_float(value)
    if plus:
        return f"{parsed:+.1%}"
    return f"{max(0.0, min(1.0, parsed)):.1%}"


def simulation_comparison_to_markdown(
    payload: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a simulation-comparison payload as a founder-facing brief."""
    data = _as_dict(payload)
    sim_ids = _simulation_ids(data)

    lines: list[str] = []
    lines.append("# Simulation Comparison")
    lines.append("")
    lines.append(
        "Side-by-side comparison of completed simulation runs: headline "
        "winner, per-cluster conversion differences, and domain-finding "
        "consensus across the runs."
    )
    lines.append("")
    if metadata:
        generated = _safe_text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Verdict")
    lines.append("")
    summary = _summary_dict(data)
    lines.append(
        f"**{_escape_md_cell(summary.get('verdict'))}** — winner "
        f"{_escape_md_cell(summary.get('winner_label'))} "
        f"(simulation {_safe_int(summary.get('best_simulation_id'))}), "
        f"conversion spread "
        f"{_safe_float(summary.get('conversion_spread_pct'), 0.0):.1f}%."
    )
    lines.append("")

    lines.append("## Simulations Compared")
    lines.append("")
    lines.append(
        "| Label | Simulation | Conversion | Revenue | Signal | Product type | Status |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | --- | --- |")
    for idx, sim in enumerate(_as_list(data.get("simulations")), start=1):
        if not isinstance(sim, dict):
            continue
        label = chr(ord("A") + idx - 1) if idx <= 26 else f"Sim {idx}"
        lines.append(
            "| {label} | {sim_id} | {conv} | {rev} | {sig} | {ptype} | {status} |".format(
                label=label,
                sim_id=_safe_int(sim.get("simulation_id")),
                conv=_pct(sim.get("conversion_rate")),
                rev=(
                    f"${_safe_float(sim.get('revenue_projection'), 0.0):,.0f}"
                    if sim.get("revenue_projection") is not None
                    else "—"
                ),
                sig=(
                    f"{_safe_float(sim.get('signal_quality'), 0.0):.2f}"
                    if sim.get("signal_quality") is not None
                    else "—"
                ),
                ptype=_escape_md_cell(sim.get("product_type_detected")) or "—",
                status=_escape_md_cell(sim.get("status")),
            )
        )
    lines.append("")

    lines.append("## Cluster Conversion Comparison")
    lines.append("")
    clusters = _as_list(data.get("cluster_comparison"))
    if not clusters:
        lines.append("No per-cluster conversion data is available.")
    else:
        lines.append(
            "| Cluster | Weight | "
            + " | ".join(f"{label} conv" for label in _sim_labels(sim_ids))
            + " | Winner |"
        )
        lines.append(
            "| --- | ---: | "
            + " | ".join(["---:"] * len(sim_ids))
            + " | --- |"
        )
        for row in clusters:
            if not isinstance(row, dict):
                continue
            conversions = _as_dict_map(row.get("conversions"))
            lines.append(
                "| {name} | {weight} | {conv_cells} | {winner} |".format(
                    name=_escape_md_cell(row.get("cluster_name")),
                    weight=f"{_safe_float(row.get('population_weight')):.4f}",
                    conv_cells=" | ".join(
                        _pct(_lookup(conversions, sid)) for sid in sim_ids
                    ),
                    winner=_escape_md_cell(row.get("winner_label")),
                )
            )
    lines.append("")

    lines.append("## Domain Findings")
    lines.append("")
    domains = _as_list(data.get("domain_finding_comparison"))
    if not domains:
        lines.append("No domain-finding comparison is available.")
    else:
        for row in domains:
            if not isinstance(row, dict):
                continue
            severity_by_sim = _as_dict_map(row.get("severity_by_sim"))
            findings_by_sim = _as_dict_map(row.get("findings"))
            sev_parts: list[str] = []
            for sid in sim_ids:
                sev = _safe_text(_lookup(severity_by_sim, sid))
                sev_parts.append(f"{_id_label(data, sid)}: {sev or '—'}")
            finding_parts: list[str] = []
            for sid in sim_ids:
                text = _findings_text(_lookup(findings_by_sim, sid))
                if text:
                    finding_parts.append(f"{_id_label(data, sid)}: {text}")
            lines.append(
                f"- **{_escape_md_cell(row.get('domain'))}** "
                f"({_escape_md_cell(row.get('consensus'))}) — "
                f"{' · '.join(sev_parts)}."
            )
            if finding_parts:
                lines.append("  " + _escape_md_cell(" | ".join(finding_parts)))
            rec = _safe_text(row.get("recommendation"))
            if rec:
                lines.append(f"  {_escape_md_cell(rec)}")
    lines.append("")

    lines.append("---")
    lines.append("")
    footer = []
    if data.get("project_id") is not None:
        footer.append(f"Project {_safe_int(data.get('project_id'))}")
    if data.get("comparison_id"):
        footer.append(f"Comparison {_escape_md_cell(data.get('comparison_id'))}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def _sim_labels(sim_ids: list[int]) -> list[str]:
    out: list[str] = []
    for idx, sim_id in enumerate(sim_ids, start=1):
        out.append(chr(ord("A") + idx - 1) if idx <= 26 else f"Sim {sim_id}")
    return out


__all__ = [
    "simulation_comparison_to_csv",
    "simulation_comparison_to_json",
    "simulation_comparison_to_markdown",
]

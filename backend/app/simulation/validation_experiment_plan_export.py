"""CSV/JSON/Markdown export helpers for the validation experiment plan.

The validation-experiment-plan endpoint
(``GET /api/v1/simulations/{id}/validation-experiment-plan``) turns a
completed simulation's validation-ROI ranking into a concrete, sequenced
validation sprint: method, cost tier, duration, sample target, success
threshold and go/no-go rule per assumption. This module renders that same
payload for download so founders can track and share the de-risking backlog
in Sheets/Excel, feed a planning pipeline, or read a human-friendly report.

The CSV follows the lightweight multi-section convention used by the
risk-register and launch-checklist exports: an optional metadata block, a
one-row-per-key sprint summary, one row per planned experiment, and a meta
section. Missing optional fields render as blanks rather than crashing the
export. The CSV starts with a UTF-8 BOM so Excel decodes non-Latin assumption
text correctly; the JSON export emits UTF-8 with ``ensure_ascii=False`` and a
trailing newline so the same text round-trips cleanly. The Markdown export
renders a founder-facing brief with a sprint summary, per-experiment table,
narrative, and metadata footer.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

CSV_HEADERS: list[str] = [
    "rank",
    "assumption_text",
    "category",
    "roi_tier",
    "validation_roi",
    "expected_conversion_swing",
    "confidence_tier",
    "method",
    "method_label",
    "method_description",
    "cost_tier",
    "estimated_duration_days",
    "sample_target",
    "success_metric",
    "success_threshold",
    "go_no_go_rule",
    "rationale",
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
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") or (
            stripped[:1] in ("=", "+", "-", "@", "\t", "\r") and stripped != value
        ):
            return f"'{value}"
    return value


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


def _summary_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten the top-level plan fields used by the CSV summary section."""
    summary = data.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "baseline_conversion": data.get("baseline_conversion"),
        "signal_quality": data.get("signal_quality"),
        "experiment_count": summary.get("experiment_count"),
        "validate_first_count": summary.get("validate_first_count"),
        "high_value_count": summary.get("high_value_count"),
        "free_count": summary.get("free_count"),
        "low_cost_count": summary.get("low_cost_count"),
        "medium_cost_count": summary.get("medium_cost_count"),
        "sprint_days": summary.get("sprint_days"),
        "sequential_days": summary.get("sequential_days"),
        "budget_ceiling": summary.get("budget_ceiling"),
        "top_experiment": summary.get("top_experiment"),
        "narrative": data.get("narrative"),
    }


def _experiment_row(experiment: Any, rank: int) -> list[object]:
    """Render one planned experiment as a CSV row."""
    exp = _as_dict(experiment) if experiment is not None else {}
    if not exp:
        return []
    return [
        rank,
        _safe_text(exp.get("assumption_text")),
        _safe_text(exp.get("category")),
        _safe_text(exp.get("roi_tier")),
        _safe_float(exp.get("validation_roi")),
        _safe_float(exp.get("expected_conversion_swing")),
        _safe_text(exp.get("confidence_tier")),
        _safe_text(exp.get("method")),
        _safe_text(exp.get("method_label")),
        _safe_text(exp.get("method_description")),
        _safe_text(exp.get("cost_tier")),
        _safe_float(exp.get("estimated_duration_days")),
        _safe_text(exp.get("sample_target")),
        _safe_text(exp.get("success_metric")),
        _safe_text(exp.get("success_threshold")),
        _safe_text(exp.get("go_no_go_rule")),
        _safe_text(exp.get("rationale")),
    ]


def validation_experiment_plan_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-experiment-plan payload as a multi-section CSV."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Sprint summary section.
    _write_row(writer, ["section", "Validation Sprint Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_dict(data).items():
        _write_row(writer, [key, _safe_text(value)])
    _write_row(writer, [])

    # Planned experiments.
    _write_row(writer, ["section", "Experiments"])
    _write_row(writer, list(CSV_HEADERS))
    experiments = data.get("experiments") or []
    wrote_experiment = False
    for rank, raw_experiment in enumerate(experiments, start=1):
        row = _experiment_row(raw_experiment, rank)
        if not row:
            continue
        _write_row(writer, row)
        wrote_experiment = True
    if not wrote_experiment:
        _write_row(writer, [""] * len(CSV_HEADERS))
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
                _write_row(writer, [key, _safe_text(value)])

    # UTF-8 BOM: without it, Excel on Windows guesses ANSI and mangles
    # non-Latin assumption text (emoji, accents, CJK) even though the
    # response advertises charset=utf-8.
    return "\ufeff" + buffer.getvalue()


def validation_experiment_plan_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-experiment-plan payload as an indented JSON doc."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "validation_experiment_plan": _as_dict(payload),
        },
        default=str,
        indent=2,
        ensure_ascii=False,
    ) + "\n"


_SUMMARY_LABELS: dict[str, str] = {
    "simulation_id": "Simulation",
    "project_id": "Project",
    "status": "Status",
    "baseline_conversion": "Baseline conversion",
    "signal_quality": "Signal quality",
    "experiment_count": "Experiments",
    "validate_first_count": "Validate-first",
    "high_value_count": "High-value",
    "free_count": "Free",
    "low_cost_count": "Low cost",
    "medium_cost_count": "Medium cost",
    "sprint_days": "Sprint (parallel, days)",
    "sequential_days": "Sequential (days)",
    "budget_ceiling": "Budget ceiling",
    "top_experiment": "Top experiment",
    "narrative": "Narrative",
}

_EXP_HEADERS: tuple[str, ...] = (
    "assumption_text",
    "category",
    "roi_tier",
    "validation_roi",
    "expected_conversion_swing",
    "confidence_tier",
    "method_label",
    "cost_tier",
    "estimated_duration_days",
    "success_threshold",
)


def _escape_md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _escape_md(value)
    return f"{f * 100:.1f}%"


def validation_experiment_plan_to_markdown(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a validation-experiment-plan payload as a founder-facing brief."""
    data = _as_dict(payload)
    summary = _summary_dict(data)
    experiments = data.get("experiments") or []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    lines: list[str] = []
    lines.append("# Validation Sprint Plan")
    lines.append("")
    lines.append(
        "Concrete experiments to de-risk the highest-ROI assumptions from your "
        "simulation, ordered by impact."
    )
    lines.append("")

    if metadata and metadata.get("generated_at"):
        lines.append(f"*Generated: {_escape_md(metadata['generated_at'])}*")
        lines.append("")

    lines.append("## Sprint Summary")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for key, label in _SUMMARY_LABELS.items():
        value = summary.get(key)
        if value is None:
            cell = "—"
        elif isinstance(value, str) and "%" in value or isinstance(value, str) and value.startswith("0."):
            cell = _md_pct(value)
        elif isinstance(value, str):
            cell = _escape_md(value)
        else:
            cell = _escape_md(value)
        lines.append(f"| {label} | {cell} |")
    lines.append("")

    narrative = data.get("narrative")
    if narrative:
        lines.append("## Narrative")
        lines.append("")
        lines.append(_escape_md(narrative))
        lines.append("")

    exp_list = list(experiments)
    if exp_list:
        lines.append("## Planned Experiments")
        lines.append("")
        header = (
            "| # | Assumption | Category | ROI tier | ROI | Swing | "
            "Confidence | Method | Cost | Dur (days) | Success |"
        )
        lines.append(header)
        lines.append("| ---: | --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | --- |")
        for rank, raw in enumerate(exp_list, start=1):
            exp = _as_dict(raw) if raw is not None else {}
            if not exp:
                continue
            lines.append(
                f"| {rank} "
                f"| {_escape_md(exp.get('assumption_text', ''))} "
                f"| {_escape_md(exp.get('category', ''))} "
                f"| {_escape_md(exp.get('roi_tier', ''))} "
                f"| {_md_pct(exp.get('validation_roi'))} "
                f"| {_md_pct(exp.get('expected_conversion_swing'))} "
                f"| {_escape_md(exp.get('confidence_tier', ''))} "
                f"| {_escape_md(exp.get('method_label', ''))} "
                f"| {_escape_md(exp.get('cost_tier', ''))} "
                f"| {exp.get('estimated_duration_days', '—')} "
                f"| {_escape_md(exp.get('success_threshold', ''))} |"
            )
        lines.append("")

        lines.append("### Go/No-Go Rules")
        lines.append("")
        for rank, raw in enumerate(exp_list, start=1):
            exp = _as_dict(raw) if raw is not None else {}
            if not exp:
                continue
            rule = exp.get("go_no_go_rule", "")
            if rule:
                lines.append(
                    f"{rank}. **{_escape_md(exp.get('method_label', 'Experiment'))}** "
                    f"— {_escape_md(rule)}"
                )
        lines.append("")
    else:
        lines.append("## Planned Experiments")
        lines.append("")
        lines.append(
            "_No assumptions currently need an experiment — the ones worth "
            "testing are either already validated or have minimal conversion "
            "impact._"
        )
        lines.append("")

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
    footer = ["Validation sprint plan"]
    if metadata:
        user_id = metadata.get("user_id")
        if user_id is not None:
            footer.append(f"User {user_id}")
        sim_id = metadata.get("simulation_id")
        if sim_id is not None:
            footer.append(f"Simulation {sim_id}")
        if metadata.get("generated_at"):
            footer.append(f"Generated {_escape_md(metadata['generated_at'])}")
    lines.append(f"*{' · '.join(footer)}*")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


__all__ = [
    "validation_experiment_plan_to_csv",
    "validation_experiment_plan_to_json",
    "validation_experiment_plan_to_markdown",
]

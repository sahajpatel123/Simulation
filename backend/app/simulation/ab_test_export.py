"""CSV / JSON / Markdown export helpers for the A/B experiment registry.

The experiment endpoints give founders a durable per-project registry of
landing-page tests plus a portfolio digest, but until now there was no way
to pull that evidence trail into a spreadsheet, Notion doc, or external
tool. This module renders a project's logged experiments for download:

* CSV — a multi-section spreadsheet (metadata, portfolio summary, one row
  per experiment with arms, verdict, and statistical snapshot) for
  Sheets/Excel.
* JSON — a machine-readable envelope (metadata + summary + hydrated
  experiments) for tools and integrations.
* Markdown — a concise founder-facing brief for docs or an investor update.

The module is pure and defensive: malformed rows, missing snapshot fields,
and scalar values in list positions degrade to safe defaults without
raising, and CSV cells are guarded against spreadsheet formula injection
— including formulas hidden behind leading whitespace or control
characters.
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from app.schemas.ab_test import AbTestExperimentOut
from app.simulation.ab_test_summary import build_ab_test_summary

FORMAT_VERSION = "1"


def _as_dict(item: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return {}


def _as_list(value: Any) -> list[Any]:
    """Coerce an optional sequence to a list, dropping malformed scalars."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


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


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, parsed)


_FORMULA_STARTERS: tuple[str, ...] = ("=", "+", "-", "@")
_CONTROL_STARTERS: tuple[str, ...] = ("\t", "\r", "\n")


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with a formula starter (``=``, ``+``, ``-``, ``@``) or
    with a tab / carriage return / newline are prefixed with a single quote
    so Excel, LibreOffice, and Google Sheets treat them as literal text.
    Formula starters hidden behind leading whitespace are also caught,
    because spreadsheet parsers trim whitespace before evaluating a cell.
    """
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped[:1] in _FORMULA_STARTERS or value[:1] in _CONTROL_STARTERS:
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with formula-injection guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def _analysis_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return the nested analysis snapshot, defaulting to an empty dict."""
    analysis = data.get("analysis")
    if isinstance(analysis, dict):
        return analysis
    return {}


def _variant(
    data: dict[str, Any],
    *,
    which: str,
) -> dict[str, Any]:
    """Return one observed arm from the nested analysis snapshot."""
    analysis = _analysis_dict(data)
    variant = analysis.get(which)
    if isinstance(variant, dict):
        return variant
    return {}


def _row_value(value: Any) -> object:
    """Blank out ``None`` so CSV cells stay empty instead of 'None'."""
    return "" if value is None else value


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key, default in (
        ("generated_at", ""),
        ("user_id", ""),
        ("format_version", FORMAT_VERSION),
        ("project_id", ""),
        ("experiment_count", ""),
    ):
        value = metadata.get(key, default)
        if value is None:
            value = default
        rows.append((key, "" if value is None else str(value)))
    return rows


def _safe_bool(value: Any) -> bool:
    """Coerce a defensive boolean from a stored value.

    Real booleans pass through unchanged; numeric and string spellings are
    coerced explicitly so a malformed ``"False"`` / ``"0"`` row can never
    silently flip into ``True``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _summary_dict(experiments: Sequence[Any], project_id: int) -> dict[str, Any]:
    """Roll hydrated experiments into the digest shape used by the API."""
    adapters: list[SimpleNamespace] = []
    for item in experiments:
        data = _as_dict(item)
        analysis = _analysis_dict(data)
        variant_a = _variant(data, which="variant_a")
        variant_b = _variant(data, which="variant_b")
        absolute_uplift = (
            data.get("absolute_uplift")
            if data.get("absolute_uplift") is not None
            else analysis.get("absolute_uplift")
        )
        relative_uplift_pct = (
            data.get("relative_uplift_pct")
            if data.get("relative_uplift_pct") is not None
            else analysis.get("relative_uplift_pct")
        )
        adapters.append(
            SimpleNamespace(
                id=_safe_int(data.get("id")),
                name=_safe_text(data.get("name")),
                verdict=_safe_text(data.get("verdict")),
                significant=_safe_bool(data.get("significant")),
                winner=data.get("winner"),
                absolute_uplift=absolute_uplift,
                relative_uplift_pct=relative_uplift_pct,
                visitors_a=_safe_int(variant_a.get("visitors")),
                conversions_a=_safe_int(variant_a.get("conversions")),
                visitors_b=_safe_int(variant_b.get("visitors")),
                conversions_b=_safe_int(variant_b.get("conversions")),
                created_at=data.get("created_at"),
            )
        )
    return build_ab_test_summary(adapters, project_id)


def _experiment_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten one experiment into named fields shared by CSV / Markdown."""
    analysis = _analysis_dict(data)
    variant_a = _variant(data, which="variant_a")
    variant_b = _variant(data, which="variant_b")
    confidence_interval = analysis.get("confidence_interval") or {}
    if not isinstance(confidence_interval, dict):
        confidence_interval = {}
    recommendations = _as_list(analysis.get("recommendations"))
    absolute_uplift = (
        data.get("absolute_uplift")
        if data.get("absolute_uplift") is not None
        else analysis.get("absolute_uplift")
    )
    relative_uplift_pct = (
        data.get("relative_uplift_pct")
        if data.get("relative_uplift_pct") is not None
        else analysis.get("relative_uplift_pct")
    )
    z_score = (
        data.get("z_score")
        if data.get("z_score") is not None
        else analysis.get("z_score")
    )
    p_value = (
        data.get("p_value")
        if data.get("p_value") is not None
        else analysis.get("p_value")
    )
    return {
        "id": _safe_int(data.get("id")),
        "name": _safe_text(data.get("name")),
        "hypothesis": _safe_text(data.get("hypothesis")),
        "created_at": _safe_text(data.get("created_at")),
        "updated_at": _safe_text(data.get("updated_at")),
        "variant_a_label": _safe_text(variant_a.get("label")),
        "visitors_a": _safe_int(variant_a.get("visitors")),
        "conversions_a": _safe_int(variant_a.get("conversions")),
        "conversion_rate_a": _safe_float(variant_a.get("conversion_rate")),
        "variant_b_label": _safe_text(variant_b.get("label")),
        "visitors_b": _safe_int(variant_b.get("visitors")),
        "conversions_b": _safe_int(variant_b.get("conversions")),
        "conversion_rate_b": _safe_float(variant_b.get("conversion_rate")),
        "winner": _safe_text(data.get("winner")),
        "verdict": _safe_text(data.get("verdict")),
        "significant": _safe_text(data.get("significant")),
        "absolute_uplift": _safe_float(absolute_uplift),
        "relative_uplift_pct": _safe_float(relative_uplift_pct),
        "z_score": _safe_float(z_score),
        "p_value": p_value,
        "confidence_level": _safe_float(analysis.get("confidence_level")),
        "confidence_interval_low": _safe_float(confidence_interval.get("low")),
        "confidence_interval_high": _safe_float(confidence_interval.get("high")),
        "visitors_needed_for_observed_uplift": _safe_int(
            analysis.get("visitors_needed_for_observed_uplift")
        ),
        "visitors_needed_for_mde": _safe_int(
            analysis.get("visitors_needed_for_mde")
        ),
        "recommendations": "; ".join(
            _safe_text(recommendation) for recommendation in recommendations
        ),
        "recommendations_count": len(recommendations),
        "key_signals_count": len(_as_list(analysis.get("key_signals"))),
    }


def _experiment_row(fields: dict[str, Any]) -> list[object]:
    """Render named experiment fields as a CSV row."""
    p_value = fields["p_value"]
    return [
        fields["id"],
        fields["name"],
        fields["hypothesis"],
        fields["created_at"],
        fields["updated_at"],
        fields["variant_a_label"],
        fields["visitors_a"],
        fields["conversions_a"],
        fields["conversion_rate_a"],
        fields["variant_b_label"],
        fields["visitors_b"],
        fields["conversions_b"],
        fields["conversion_rate_b"],
        fields["winner"],
        fields["verdict"],
        fields["significant"],
        fields["absolute_uplift"],
        fields["relative_uplift_pct"],
        fields["z_score"],
        (
            ""
            if p_value is None
            else f"{_safe_float(p_value):.8f}".rstrip("0").rstrip(".")
        ),
        fields["confidence_level"],
        fields["confidence_interval_low"],
        fields["confidence_interval_high"],
        fields["visitors_needed_for_observed_uplift"],
        fields["visitors_needed_for_mde"],
        fields["recommendations"],
        fields["recommendations_count"],
        fields["key_signals_count"],
    ]


def ab_test_experiments_to_csv(
    experiments: Sequence[Any],
    *,
    project_id: int,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project's experiment portfolio as a multi-section CSV string."""
    rows = [_as_dict(item) for item in experiments]
    rows = [row for row in rows if row]
    summary = _summary_dict(experiments, project_id)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Portfolio summary section.
    _write_row(writer, ["section", "A/B Experiment Portfolio Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in summary.items():
        if isinstance(value, dict):
            value = json.dumps(value, default=str)
        _write_row(writer, [key, _row_value(value)])
    _write_row(writer, [])

    # Per-experiment registry.
    _write_row(writer, ["section", "Experiments"])
    _write_row(
        writer,
        [
            "id",
            "name",
            "hypothesis",
            "created_at",
            "updated_at",
            "variant_a_label",
            "visitors_a",
            "conversions_a",
            "conversion_rate_a",
            "variant_b_label",
            "visitors_b",
            "conversions_b",
            "conversion_rate_b",
            "winner",
            "verdict",
            "significant",
            "absolute_uplift",
            "relative_uplift_pct",
            "z_score",
            "p_value",
            "confidence_level",
            "confidence_interval_low",
            "confidence_interval_high",
            "visitors_needed_for_observed_uplift",
            "visitors_needed_for_mde",
            "recommendations",
            "recommendations_count",
            "key_signals_count",
        ],
    )
    for data in rows:
        _write_row(writer, _experiment_row(_experiment_fields(data)))

    return buffer.getvalue()


def ab_test_experiments_to_json(
    experiments: Sequence[Any],
    *,
    project_id: int,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project's experiment portfolio as an indented JSON document."""
    payload = {
        "metadata": metadata or {},
        "project_id": _safe_int(project_id),
        "summary": _summary_dict(experiments, project_id),
        "experiments": [
            (
                item.model_dump(mode="json")
                if isinstance(item, AbTestExperimentOut)
                else _as_dict(item)
            )
            for item in experiments
            if _as_dict(item)
        ],
    }
    return json.dumps(payload, default=str, indent=2)


def _escape_md_cell(value: Any) -> str:
    """Escape pipe and newline characters for a Markdown table cell."""
    return _safe_text(value).replace("|", "\\|").replace("\n", " ")


def _fmt_rate(value: Any) -> str:
    """Format a 0..1 fraction as a percentage, blank for missing values."""
    parsed = _safe_float(value)
    if parsed == 0.0 and value not in (0, 0.0, "0", "0.0"):
        return "—"
    return f"{parsed * 100:.2f}%"


def _fmt_pct_points(value: Any) -> str:
    """Format an already-percentage figure (e.g. relative uplift)."""
    if value is None:
        return "—"
    parsed = _safe_float(value)
    return f"{parsed:+.2f}%"


def _fmt_signed(value: Any) -> str:
    if value is None:
        return "—"
    parsed = _safe_float(value)
    return f"{parsed:+.4f}"


def _summary_lines(summary: dict[str, Any]) -> list[tuple[str, str]]:
    """Curated key/value pairs for the Markdown summary table."""
    verdict_counts = summary.get("verdict_counts") or {}
    if isinstance(verdict_counts, dict):
        verdict_text = ", ".join(
            f"{verdict}: {count}" for verdict, count in verdict_counts.items()
        )
    else:
        verdict_text = _safe_text(verdict_counts)
    return [
        ("Total Experiments", _safe_int(summary.get("total_experiments"))),
        ("Verdict Counts", verdict_text),
        ("Significant", _safe_int(summary.get("significant_count"))),
        ("Trending", _safe_int(summary.get("trending_count"))),
        ("Inconclusive", _safe_int(summary.get("inconclusive_count"))),
        ("Insufficient Data", _safe_int(summary.get("insufficient_data_count"))),
        ("Significant Win Rate", _fmt_rate(summary.get("significant_win_rate"))),
        ("Control Won", _safe_int(summary.get("control_won_count"))),
        ("Challenger Won", _safe_int(summary.get("challenger_won_count"))),
        ("Total Visitors", _safe_int(summary.get("total_visitors"))),
        ("Total Conversions", _safe_int(summary.get("total_conversions"))),
        (
            "Overall Conversion Rate",
            _fmt_rate(summary.get("overall_conversion_rate")),
        ),
        ("Mean Absolute Uplift", _fmt_signed(summary.get("mean_absolute_uplift"))),
        (
            "Median Absolute Uplift",
            _fmt_signed(summary.get("median_absolute_uplift")),
        ),
        (
            "Median Relative Uplift",
            _fmt_pct_points(summary.get("median_relative_uplift_pct")),
        ),
        ("Next Action", _safe_text(summary.get("next_action"))),
    ]


def ab_test_experiments_to_markdown(
    experiments: Sequence[Any],
    *,
    project_id: int,
    project_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a project's experiment portfolio as a founder-facing brief."""
    rows = [_as_dict(item) for item in experiments]
    rows = [row for row in rows if row]
    summary = _summary_dict(experiments, project_id)
    title = (project_name or "TheCee").strip() or "TheCee"
    lines: list[str] = []
    lines.append(f"# {_escape_md_cell(title)} — A/B Experiment Portfolio")
    lines.append("")
    lines.append(
        "This brief rolls every logged landing-page A/B experiment into one "
        "evidence trail: verdicts, observed arms, and the tests worth shipping."
    )
    lines.append("")
    if metadata:
        generated_at = metadata.get("generated_at", "")
        lines.append(f"- Generated: {_escape_md_cell(generated_at)}")
    lines.append(f"- Project: {_safe_int(project_id)}")
    lines.append(f"- Experiments: {_safe_int(summary.get('total_experiments'))}")
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Key | Value |")
    lines.append("| --- | --- |")
    for key, value in _summary_lines(summary):
        lines.append(f"| {_escape_md_cell(key)} | {_escape_md_cell(value)} |")
    lines.append("")

    lines.append("## Experiments")
    lines.append("")
    if rows:
        lines.append(
            "| ID | Name | Verdict | Significant | Winner | Visitors | "
            "Conversions | Conversion Rate | Absolute Uplift | Relative Uplift "
            "| P-Value | Created |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for data in rows:
            fields = _experiment_fields(data)
            visitors = fields["visitors_a"] + fields["visitors_b"]
            conversions = fields["conversions_a"] + fields["conversions_b"]
            p_value = fields["p_value"]
            lines.append(
                "| {id} | {name} | {verdict} | {significant} | {winner} | "
                "{visitors} | {conversions} | {rate} | {uplift} | {relative} "
                "| {p_value} | {created} |".format(
                    id=fields["id"],
                    name=_escape_md_cell(fields["name"]),
                    verdict=_escape_md_cell(fields["verdict"]),
                    significant=_escape_md_cell(fields["significant"]),
                    winner=_escape_md_cell(fields["winner"]),
                    visitors=visitors,
                    conversions=conversions,
                    rate=_fmt_rate(conversions / visitors) if visitors > 0 else "—",
                    uplift=_fmt_signed(fields["absolute_uplift"]),
                    relative=_fmt_pct_points(fields["relative_uplift_pct"]),
                    p_value=(
                        "—"
                        if p_value is None
                        else f"{_safe_float(p_value):.6f}"
                    ),
                    created=_escape_md_cell(fields["created_at"]),
                )
            )
    else:
        lines.append("No experiments logged yet.")
    lines.append("")

    lines.append("## Recommendations")
    lines.append("")
    recommendation_rows: list[tuple[str, list[str]]] = []
    for data in rows:
        analysis = _analysis_dict(data)
        recommendations = _as_list(analysis.get("recommendations"))
        if recommendations:
            recommendation_rows.append(
                (
                    _safe_text(data.get("name")),
                    [_safe_text(item) for item in recommendations],
                )
            )
    if recommendation_rows:
        for name, recommendations in recommendation_rows:
            for recommendation in recommendations:
                lines.append(
                    f"- {_escape_md_cell(name)}: "
                    f"{_escape_md_cell(recommendation)}"
                )
    else:
        lines.append("No actionable recommendations are recorded yet.")
    lines.append("")

    next_action = _safe_text(summary.get("next_action"))
    if next_action:
        lines.append("## Next Action")
        lines.append("")
        lines.append(next_action)
        lines.append("")

    return "\n".join(lines)


__all__ = [
    "FORMAT_VERSION",
    "ab_test_experiments_to_csv",
    "ab_test_experiments_to_json",
    "ab_test_experiments_to_markdown",
]

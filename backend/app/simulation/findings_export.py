"""
Pure helpers for exporting a simulation's domain findings.

The route layer pulls the owned simulation and passes its
``results_json`` here; this module stays deterministic and handles the
versioned finding shapes (``domain_findings``, ``findings``, or a raw
list) with safe defaults for missing fields. It supports both
spreadsheet-friendly CSV and a founder-facing Markdown brief.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

from app.simulation.export_utils import write_row


def _coerce_results(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return None
        if isinstance(parsed, (dict, list)):
            return parsed
    return None


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


def extract_findings(results: Any) -> list[dict[str, Any]]:
    """Pull a list of finding dicts from a simulation's results_json."""
    payload = _coerce_results(results)
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    for key in ("domain_findings", "findings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def findings_to_csv(
    findings: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    simulation_id: int | None = None,
    project_id: int | None = None,
) -> str:
    """Render findings as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _safe_text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _safe_text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _safe_text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(
        writer,
        [
            "simulation_id",
            "project_id",
            "severity",
            "architect_name",
            "cluster_id",
            "cluster_name",
            "finding",
            "metric_affected",
            "recommended_action",
            "conversion_impact",
        ],
    )
    for finding in findings:
        write_row(
            writer,
            [
                _safe_text(simulation_id),
                _safe_text(project_id),
                _safe_text(finding.get("severity", "INFO")).upper(),
                _safe_text(finding.get("architect_name", "")),
                _safe_text(finding.get("cluster_id", "")),
                _safe_text(finding.get("cluster_name", "")),
                _safe_text(finding.get("finding", "")),
                _safe_text(finding.get("metric_affected", "")),
                _safe_text(finding.get("recommended_action", "")),
                f"{_safe_float(finding.get('conversion_impact')):.4f}",
            ],
        )
    return buffer.getvalue()


def findings_to_markdown(
    findings: list[dict[str, Any]],
    *,
    simulation_id: int | None = None,
    project_id: int | None = None,
    project_name: str | None = None,
    primary_failure_domain: str | None = None,
    metadata: dict[str, Any] | None = None,
    max_table_rows: int = 15,
) -> str:
    """Render domain findings as a founder-readable Markdown brief.

    Unlike the CSV/JSON exports (which are spreadsheet/tooling-first), this
    output is meant to be pasted straight into a doc, Notion page, or investor
    update. It includes a short header, a severity/impact roll-up, the primary
    failure domain (when the caller has one), the top findings in a table, and
    grouped recommended actions so the founder leaves with a next-steps list.
    Pass ``max_table_rows=0`` to suppress the top-findings table entirely;
    the summary and recommended actions are still emitted.

    The function stays pure and defensive: missing fields, malformed rows, and
    unsupported severities all degrade to safe defaults without raising.
    """
    rows = _normalise_findings(findings)
    critical = [row for row in rows if row["severity"] == "CRITICAL"]
    warning = [row for row in rows if row["severity"] == "WARNING"]
    info = [row for row in rows if row["severity"] == "INFO"]
    other = [row for row in rows if row["severity"] not in ("CRITICAL", "WARNING", "INFO")]
    total_impact = sum(_safe_float(row.get("conversion_impact")) for row in rows)
    table_limit = max(0, int(max_table_rows))
    top_rows = rows[:table_limit] if table_limit else []

    lines: list[str] = []
    title = (project_name or "TheCee").strip() or "TheCee"
    lines.append(f"# {_escape_md_cell(title)} — Findings Brief")
    lines.append("")
    lines.append(
        "Domain findings are ranked by conversion impact and benchmarked "
        "against healthy thresholds for each consumer cluster."
    )
    lines.append("")

    if metadata:
        generated = _safe_text(metadata.get("generated_at"))
        if generated:
            lines.append(f"*Generated: {_escape_md_cell(generated)}*")
            lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | ---: |")
    lines.append(f"| Total findings | {len(rows)} |")
    lines.append(f"| Critical | {len(critical)} |")
    lines.append(f"| Warning | {len(warning)} |")
    lines.append(f"| Info | {len(info)} |")
    if other:
        lines.append(f"| Other | {len(other)} |")
    lines.append(f"| Combined conversion impact | {total_impact:.2%} |")
    if primary_failure_domain:
        lines.append(f"| Primary failure domain | {_escape_md_cell(str(primary_failure_domain))} |")
    lines.append("")

    lines.append("## Top Findings")
    lines.append("")
    if not rows:
        lines.append("No domain findings available.")
        lines.append("")
        return "\n".join(lines).strip() + "\n"

    if top_rows:
        lines.append("| # | Severity | Architect | Cluster | Finding | Impact |")
        lines.append("| --- | --- | --- | --- | --- | ---: |")
        for index, row in enumerate(top_rows, start=1):
            severity = _severity_label(row["severity"])
            architect = _escape_md_cell(_safe_text(row.get("architect_name")))
            cluster = _escape_md_cell(_safe_text(row.get("cluster_name")))
            finding = _escape_md_cell(_safe_text(row.get("finding")))
            impact = _safe_float(row.get("conversion_impact"))
            lines.append(
                f"| {index} | {severity} | {architect} | {cluster} | {finding} | {impact:.2%} |"
            )
        lines.append("")
    else:
        lines.append("")

    actions = _group_recommended_actions(rows)
    lines.append("## Recommended Actions")
    lines.append("")
    if not actions:
        lines.append("No recommended actions are available for the current findings.")
    else:
        for action, impacted in actions:
            bullets = " ".join(f"`{_escape_md_cell(str(item))}`" for item in impacted[:6])
            lines.append(f"- **{_escape_md_cell(action)}**")
            if bullets:
                lines.append(f"  {bullets}")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def _normalise_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop non-dict rows and upper-case severities so grouping is stable."""
    out: list[dict[str, Any]] = []
    for row in findings or []:
        if not isinstance(row, dict):
            continue
        severity = str(row.get("severity", "INFO") or "INFO").upper().strip()
        out.append({**row, "severity": severity})
    return out


def _severity_label(severity: str) -> str:
    return {
        "CRITICAL": "🔴 Critical",
        "WARNING": "🟠 Warning",
        "INFO": "🟢 Info",
    }.get(severity, "—")


_SEVERITY_RANK: dict[str, int] = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _group_recommended_actions(
    rows: list[dict[str, Any]],
) -> list[tuple[str, list[str]]]:
    """Group recommended actions into ordered buckets with affected clusters.

    Severity-weighted, then by total conversion impact, then alphabetically so
    output is deterministic across runs.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        action = _safe_text(row.get("recommended_action")).strip()
        if not action:
            action = "Review and improve this metric"
        entry = buckets.setdefault(
            action,
            {
                "impact": 0.0,
                "severity_rank": 2,
                "clusters": [],
                "seen": set(),
            },
        )
        entry["impact"] += _safe_float(row.get("conversion_impact"))
        severity = row["severity"]
        entry["severity_rank"] = min(entry["severity_rank"], _SEVERITY_RANK.get(severity, 2))
        cluster = _safe_text(row.get("cluster_name"))
        if cluster and cluster not in entry["seen"]:
            entry["seen"].add(cluster)
            entry["clusters"].append(cluster)

    ordered = sorted(
        buckets.items(),
        key=lambda pair: (
            pair[1]["severity_rank"],
            -pair[1]["impact"],
            pair[0].lower(),
        ),
    )
    return [(action, entry["clusters"]) for action, entry in ordered]


def _escape_md_cell(value: str) -> str:
    """Escape pipe and newline characters so finding text cannot break tables."""
    return re.sub(r"[\r\n]+", " ", value).replace("|", "\\|")


def findings_count_to_csv(
    row: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a findings-count row as a single-row CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        write_row(writer, ["generated_at", _safe_text(metadata.get("generated_at"))])
        write_row(writer, ["user_id", _safe_text(metadata.get("user_id"))])
        write_row(writer, ["format_version", _safe_text(metadata.get("format_version", "1"))])
        write_row(writer, [])

    write_row(writer, ["simulation_id", "findings_count"])
    write_row(
        writer,
        [
            _safe_text(row.get("simulation_id")),
            _safe_text(row.get("findings_count")),
        ],
    )
    return buffer.getvalue()


__all__ = [
    "extract_findings",
    "findings_count_to_csv",
    "findings_to_csv",
    "findings_to_markdown",
]

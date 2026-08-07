"""
Pure helper for exporting a simulation's domain findings as CSV.

The route layer pulls the owned simulation and passes its
``results_json`` here; this module stays deterministic and handles the
versioned finding shapes (``domain_findings``, ``findings``, or a raw
list) with safe defaults for missing fields.
"""
from __future__ import annotations

import csv
import io
import json
import math
from typing import Any


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
) -> str:
    """Render findings as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    if metadata:
        writer.writerow(["generated_at", _safe_text(metadata.get("generated_at"))])
        writer.writerow(["user_id", _safe_text(metadata.get("user_id"))])
        writer.writerow(["format_version", _safe_text(metadata.get("format_version", "1"))])
        writer.writerow([])

    writer.writerow(
        [
            "severity",
            "architect_name",
            "cluster_id",
            "cluster_name",
            "finding",
            "metric_affected",
            "recommended_action",
            "conversion_impact",
        ]
    )
    for finding in findings:
        writer.writerow(
            [
                _safe_text(finding.get("severity", "INFO")).upper(),
                _safe_text(finding.get("architect_name", "")),
                _safe_text(finding.get("cluster_id", "")),
                _safe_text(finding.get("cluster_name", "")),
                _safe_text(finding.get("finding", "")),
                _safe_text(finding.get("metric_affected", "")),
                _safe_text(finding.get("recommended_action", "")),
                f"{_safe_float(finding.get('conversion_impact')):.4f}",
            ]
        )
    return buffer.getvalue()


__all__ = [
    "extract_findings",
    "findings_to_csv",
]

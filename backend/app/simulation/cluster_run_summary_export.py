"""CSV/JSON export helpers for per-simulation cluster run summaries.

``cluster_run_summaries`` rows are the calibration layer's per-cluster
audit trail: how many agents were assigned and converted, the funnel drop
state distribution, the primary drop trigger, architect scores and
per-cluster signal quality. They back several dashboard reads (funnel
diagnosis, market concentration, cohort retention) but were not previously
downloadable.

This module renders them as:

* CSV - a metadata block, a compact summary section and one row per cluster
  (JSONB columns rendered as compact JSON strings) so founders and
  operators can inspect a run in a spreadsheet;
* JSON - the raw machine-readable payload so BI pipelines can consume the
  full nested structures without CSV parsing.

The module stays pure and defensive: malformed rows, non-finite numbers,
missing cluster names and empty result sets degrade to safe values instead
of raising, and CSV cells are guarded against spreadsheet formula
injection.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

FORMAT_VERSION: str = "1"

_ROW_FIELDS: tuple[str, ...] = (
    "id",
    "cluster_id",
    "agents_assigned",
    "agents_converted",
    "conversion_rate",
    "drop_state_distribution",
    "mean_drop_state",
    "architect_scores",
    "primary_drop_trigger",
    "signal_quality",
    "claim_confidence_distribution",
    "product_type",
    "created_at",
)

CSV_HEADERS: list[str] = [
    "id",
    "cluster_id",
    "cluster_name",
    "agents_assigned",
    "agents_converted",
    "conversion_rate",
    "mean_drop_state",
    "primary_drop_trigger",
    "drop_state_distribution",
    "architect_scores",
    "signal_quality",
    "claim_confidence_distribution",
    "product_type",
    "created_at",
]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)


def _safe_float(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _safe_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_rate(value: Any) -> float:
    """Coerce a conversion-rate-like value into ``[0.0, 1.0]``."""
    parsed = _optional_float(value)
    if parsed is None:
        return 0.0
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
    """Render a JSONB cell as compact, deterministic JSON text."""
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
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if value[:1] in ("=", "+", "-", "@", "\t", "\r") or (
            stripped[:1] in ("=", "+", "-", "@", "\t", "\r")
            and stripped != value
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


def _summary_value(value: Any) -> object:
    """Render one summary cell, preserving integer identity/count fields."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return _safe_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _safe_float(value)
    return _safe_text(value)


def _row_value(row: Any, key: str) -> Any:
    """Read one field from a dict-like or ORM-like cluster summary row."""
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _coerce_row(row: Any) -> dict[str, Any]:
    return {key: _row_value(row, key) for key in _ROW_FIELDS}


def build_cluster_run_summary_export(
    rows: list[Any],
    *,
    simulation_id: int,
    project_id: int,
    status: str,
    cluster_names: dict[str, str] | None = None,
    created_at: Any = None,
) -> dict[str, Any]:
    """Compose the per-simulation cluster-run-summary export payload.

    ``rows`` may be SQLAlchemy ORM objects, plain dicts, or any object with
    the model's attribute names. ``cluster_names`` enriches cluster IDs
    with human-readable names when supplied; unknown IDs fall back to the
    ID itself so the export stays self-contained.
    """
    names = cluster_names or {}
    normalized: list[dict[str, Any]] = []
    total_assigned = 0
    total_converted = 0

    for raw in rows:
        if raw is None:
            continue
        row = _coerce_row(raw)
        cluster_id = _safe_text(row.get("cluster_id"))
        assigned = _safe_int(row.get("agents_assigned"))
        converted = _safe_int(row.get("agents_converted"))
        total_assigned += assigned
        total_converted += converted
        normalized.append(
            {
                "id": _safe_int(row.get("id")),
                "cluster_id": cluster_id,
                "cluster_name": _safe_text(names.get(cluster_id, cluster_id)),
                "agents_assigned": assigned,
                "agents_converted": converted,
                "conversion_rate": _bounded_rate(row.get("conversion_rate")),
                "drop_state_distribution": _json_safe(
                    row.get("drop_state_distribution")
                ),
                "mean_drop_state": _safe_text(row.get("mean_drop_state")),
                "architect_scores": _json_safe(row.get("architect_scores")),
                "primary_drop_trigger": _safe_text(row.get("primary_drop_trigger")),
                "signal_quality": _optional_float(row.get("signal_quality")),
                "claim_confidence_distribution": _json_safe(
                    row.get("claim_confidence_distribution")
                ),
                "product_type": _safe_text(row.get("product_type")),
                "created_at": _safe_text(row.get("created_at")),
            }
        )

    agents_weighted_conversion: float | None = None
    if total_assigned > 0:
        agents_weighted_conversion = round(
            max(0.0, min(1.0, total_converted / total_assigned)),
            6,
        )

    return {
        "simulation_id": simulation_id,
        "project_id": project_id,
        "status": status,
        "created_at": _safe_text(created_at),
        "total_clusters": len(normalized),
        "total_agents_assigned": total_assigned,
        "total_agents_converted": total_converted,
        "agents_weighted_conversion_rate": agents_weighted_conversion,
        "rows": normalized,
    }


def cluster_run_summary_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cluster-run-summary payload as a multi-section CSV string."""
    data = payload if isinstance(payload, dict) else {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Cluster Run Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "simulation_id",
        "project_id",
        "status",
        "created_at",
        "total_clusters",
        "total_agents_assigned",
        "total_agents_converted",
        "agents_weighted_conversion_rate",
    )
    for key in summary_keys:
        _write_row(writer, [key, _summary_value(data.get(key))])
    _write_row(writer, [])

    # One row per cluster.
    _write_row(writer, ["section", "Cluster Run Rows"])
    _write_row(writer, CSV_HEADERS)
    for row in data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        _write_row(
            writer,
            [
                _safe_int(row.get("id")),
                _safe_text(row.get("cluster_id")),
                _safe_text(row.get("cluster_name")),
                _safe_int(row.get("agents_assigned")),
                _safe_int(row.get("agents_converted")),
                _safe_float(row.get("conversion_rate")),
                _safe_text(row.get("mean_drop_state")),
                _safe_text(row.get("primary_drop_trigger")),
                _json_text(row.get("drop_state_distribution")),
                _json_text(row.get("architect_scores")),
                (
                    ""
                    if row.get("signal_quality") is None
                    else _safe_float(row.get("signal_quality"))
                ),
                _json_text(row.get("claim_confidence_distribution")),
                _safe_text(row.get("product_type")),
                _safe_text(row.get("created_at")),
            ],
        )

    # UTF-8 BOM: without it, Excel on Windows guesses ANSI and mangles
    # non-Latin cluster names even though the response advertises
    # charset=utf-8.
    return "\ufeff" + buffer.getvalue()


def cluster_run_summary_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cluster-run-summary payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": _json_safe(metadata or {}),
            "cluster_run_summaries": (
                _json_safe(payload) if isinstance(payload, dict) else {}
            ),
        },
        default=str,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


__all__ = [
    "CSV_HEADERS",
    "FORMAT_VERSION",
    "build_cluster_run_summary_export",
    "cluster_run_summary_to_csv",
    "cluster_run_summary_to_json",
]

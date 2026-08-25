"""CSV/JSON export helpers for the demand-concentration read.

The route layer in ``app/api/v1/simulations.py`` already builds the
market-concentration payload with :func:`build_market_concentration`; this
module renders that payload for download so founders can bring the HHI
summary, per-segment demand shares, fragility flags and recommendations
into a GTM planning spreadsheet or hand the raw JSON to a BI pipeline.

The CSV follows the same lightweight multi-section convention as the
risk-register and validation-experiment-plan exports: an optional metadata
block, a one-row-per-key summary section, one row per cluster demand share,
a fragility-flag list, a numbered recommendations section and a meta
section. Missing optional fields render as blanks rather than crashing the
export. The CSV starts with a UTF-8 BOM so Excel decodes non-Latin cluster
names correctly; the JSON export emits UTF-8 with ``ensure_ascii=False``
and a trailing newline so the same text round-trips cleanly.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from app.simulation.export_utils import write_row

FORMAT_VERSION: str = "1"

SEGMENT_CSV_HEADERS: list[str] = [
    "rank",
    "cluster_id",
    "cluster_name",
    "population_weight",
    "conversion_rate",
    "demand_share",
    "cumulative_share",
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


def _summary_value(value: Any) -> object:
    """Render one summary cell while preserving the original value's type.

    Integer identity/count fields (``simulation_id``, ``project_id``,
    ``total_clusters``, ``clusters_with_demand``) stay integers so a
    spreadsheet shows ``1`` instead of ``1.0``, while non-finite floats
    are still sanitised to ``0.0`` and missing fields render as blanks.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return _safe_text(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _safe_float(value)
    return _safe_text(value)


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
    write_row(writer, [_safe_csv_cell(value) for value in row])


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
    """Flatten the top-level concentration fields used by the CSV summary."""
    return {
        "simulation_id": data.get("simulation_id"),
        "project_id": data.get("project_id"),
        "status": data.get("status"),
        "signal_quality": data.get("signal_quality"),
        "total_conversion_rate": data.get("total_conversion_rate"),
        "hhi": data.get("hhi"),
        "normalized_hhi": data.get("normalized_hhi"),
        "effective_segments": data.get("effective_segments"),
        "verdict": data.get("verdict"),
        "top_1_share": data.get("top_1_share"),
        "top_3_share": data.get("top_3_share"),
        "top_5_share": data.get("top_5_share"),
        "top_cluster_id": data.get("top_cluster_id"),
        "top_cluster_name": data.get("top_cluster_name"),
        "total_clusters": data.get("total_clusters"),
        "clusters_with_demand": data.get("clusters_with_demand"),
    }


def _segment_row(item: Any, rank: int) -> list[object]:
    """Render one cluster demand share as a CSV row."""
    segment = _as_dict(item) if item is not None else {}
    if not segment:
        return []
    return [
        rank,
        _safe_text(segment.get("cluster_id")),
        _safe_text(segment.get("cluster_name")),
        _safe_float(segment.get("population_weight")),
        _safe_float(segment.get("conversion_rate")),
        _safe_float(segment.get("demand_share")),
        _safe_float(segment.get("cumulative_share")),
    ]


def market_concentration_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a market-concentration payload as a multi-section CSV."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Demand-concentration summary.
    _write_row(writer, ["section", "Demand Concentration Summary"])
    _write_row(writer, ["key", "value"])
    for key, value in _summary_dict(data).items():
        _write_row(writer, [key, _summary_value(value)])
    _write_row(writer, [])

    # Per-segment demand shares.
    _write_row(writer, ["section", "Segment Demand Shares"])
    _write_row(writer, list(SEGMENT_CSV_HEADERS))
    segments = data.get("segment_shares") or []
    wrote_segment = False
    for rank, raw_segment in enumerate(segments, start=1):
        row = _segment_row(raw_segment, rank)
        if not row:
            continue
        _write_row(writer, row)
        wrote_segment = True
    if not wrote_segment:
        _write_row(writer, [""] * len(SEGMENT_CSV_HEADERS))
    _write_row(writer, [])

    # Fragility flags.
    _write_row(writer, ["section", "Fragility Flags"])
    _write_row(writer, ["flag"])
    flags = data.get("fragility_flags") or []
    if flags:
        for flag in flags:
            _write_row(writer, [_safe_text(flag)])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    # Recommendations.
    _write_row(writer, ["section", "Recommendations"])
    _write_row(writer, ["rank", "recommendation"])
    recommendations = data.get("recommendations") or []
    if recommendations:
        for rank, recommendation in enumerate(recommendations, start=1):
            _write_row(writer, [rank, _safe_text(recommendation)])
    else:
        _write_row(writer, ["", ""])
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
    # non-Latin cluster names even though the response advertises
    # charset=utf-8.
    return "\ufeff" + buffer.getvalue()


def market_concentration_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a market-concentration payload as an indented JSON doc."""
    return (
        json.dumps(
            {
                "metadata": metadata or {},
                "market_concentration": _as_dict(payload),
            },
            default=str,
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )


__all__ = [
    "FORMAT_VERSION",
    "SEGMENT_CSV_HEADERS",
    "market_concentration_to_csv",
    "market_concentration_to_json",
]

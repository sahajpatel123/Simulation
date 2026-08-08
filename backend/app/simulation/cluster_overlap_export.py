"""CSV/JSON export helpers for the cluster-overlap matrix payload.

The route layer in ``app/api/v1/simulations.py`` builds the
cluster-overlap payload with :func:`build_cluster_overlap_matrix`; this
module renders that payload as a spreadsheet-friendly CSV so founders
can bring the "which clusters are similar enough to consolidate?"
heatmap into their planning tools, or as an indented JSON document for
machine consumers.

The CSV follows the same lightweight multi-section convention as the
sensitivity and coverage-gaps exports: an optional metadata block, a
summary section, the pairwise similarity matrix as a triangular table,
the flat pair summary, and the consolidation candidates. Missing
optional fields render as blanks rather than crashing the export.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return {}


def _value(value: Any) -> object:
    return "" if value is None else value


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    values = dict(metadata)
    requested = values.get("requested_ids", "")
    if isinstance(requested, list):
        values["requested_ids"] = ",".join(str(value) for value in requested)
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "format_version",
        "requested_ids",
    ):
        value = values.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard applied to every cell."""
    writer.writerow([_safe_csv_cell(value) for value in row])


def cluster_overlap_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cluster-overlap payload as a multi-section CSV string."""
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Cluster Overlap Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "cluster_count",
        "pair_count",
        "strong_pair_count",
        "weak_pair_count",
        "moderate_pair_count",
    )
    cluster_ids = data.get("cluster_ids") or []
    pair_summaries = data.get("pair_summaries") or []
    summary: dict[str, object] = {
        "cluster_count": len(cluster_ids),
        "pair_count": len(pair_summaries),
        "strong_pair_count": data.get("strong_pair_count", 0),
        "weak_pair_count": sum(
            1
            for pair in pair_summaries
            if isinstance(pair, dict) and pair.get("label") == "WEAK"
        ),
        "moderate_pair_count": sum(
            1
            for pair in pair_summaries
            if isinstance(pair, dict) and pair.get("label") == "MODERATE"
        ),
    }
    for key in summary_keys:
        _write_row(writer, [key, _value(summary.get(key, ""))])
    _write_row(writer, [])

    # Similarity matrix section.
    _write_row(writer, ["section", "Similarity Matrix"])
    matrix = data.get("matrix") or []
    if matrix and isinstance(matrix[0], list):
        _write_row(
            writer,
            [""] + [_value(cid) for cid in cluster_ids],
        )
        for index, row in enumerate(matrix):
            _write_row(
                writer,
                [_value(cluster_ids[index] if index < len(cluster_ids) else "")]
                + [_value(cell) for cell in row],
            )
    _write_row(writer, [])

    # Pair summaries.
    _write_row(writer, ["section", "Pair Summaries"])
    _write_row(writer, ["cluster_a", "cluster_b", "score", "label"])
    for pair in pair_summaries:
        if not isinstance(pair, dict):
            continue
        _write_row(
            writer,
            [
                _value(pair.get("cluster_a")),
                _value(pair.get("cluster_b")),
                _value(pair.get("score")),
                _value(pair.get("label")),
            ],
        )
    _write_row(writer, [])

    # Consolidation candidates.
    _write_row(writer, ["section", "Consolidation Candidates"])
    _write_row(writer, ["cluster_a", "cluster_b", "score", "label"])
    for pair in data.get("consolidation_candidates") or []:
        if not isinstance(pair, dict):
            continue
        _write_row(
            writer,
            [
                _value(pair.get("cluster_a")),
                _value(pair.get("cluster_b")),
                _value(pair.get("score")),
                _value(pair.get("label")),
            ],
        )

    return buffer.getvalue()


def cluster_overlap_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a cluster-overlap payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "cluster_overlap": _as_dict(payload),
        },
        default=str,
        indent=2,
    )


__all__ = ["cluster_overlap_to_csv", "cluster_overlap_to_json"]

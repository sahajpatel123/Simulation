"""CSV export helpers for the portfolio launch-priority digest.

``GET /simulations/portfolio-launch-priority`` already answers the
portfolio-level question "which project should I launch first?" as JSON.
This module renders that same deterministic payload as a spreadsheet-
friendly CSV (or a JSON envelope from the route layer) so founders can
share, sort, and plan in Sheets/Excel without building their own parser.

The export mirrors the digest exactly:

* **Summary** — project count, evaluated count, portfolio verdict, top
  pick, next focus, and the narrative.
* **Launch buckets** — one row per canonical bucket with the number of
  rows shown in the digest payload.
* **Launch sequence** — one row per ranked project, with the weakest
  pillar flattened into three extra columns.

The helper is pure (no SQL, no I/O) and defensive: malformed payloads
degrade to an empty but well-formed CSV instead of raising.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any

FORMAT_VERSION = "1"

# Canonical bucket order — same labels as the digest schema so the
# spreadsheet stays stable if a new bucket is ever added.
BUCKET_ORDER: tuple[str, ...] = (
    "LAUNCH_NOW",
    "CONDITIONAL_LAUNCH",
    "FIX_FIRST",
    "PARK",
)


def _as_dict(payload: Any) -> dict[str, Any]:
    """Coerce a Pydantic model or plain dict into a plain dict."""
    if hasattr(payload, "model_dump"):
        try:
            dumped = payload.model_dump()
        except Exception:
            return {}
        return dumped if isinstance(dumped, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _as_list(value: Any) -> list[Any]:
    """Coerce an optional sequence to a list, dropping malformed scalars."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _safe_text(value: Any) -> str:
    """Best-effort string for a CSV cell; ``None`` renders as blank."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _safe_float(value: Any) -> float | None:
    """Coerce to a finite float or return ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _score_text(value: Any) -> str:
    """Render a score cell without a trailing ``.0`` on whole numbers."""
    parsed = _safe_float(value)
    if parsed is None:
        return ""
    if parsed.is_integer():
        return str(int(parsed))
    return str(parsed)


def _safe_csv_cell(value: Any) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


def _write_row(writer: Any, row: list[object]) -> None:
    """Write a CSV row with the formula-injection guard on every cell."""
    writer.writerow([_safe_csv_cell(_safe_text(value)) for value in row])


def _metadata_rows(metadata: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Render the optional metadata block as ``(key, value)`` rows."""
    if not metadata:
        return []
    rows: list[tuple[str, str]] = []
    for key in (
        "generated_at",
        "user_id",
        "project_count",
        "evaluated_count",
        "portfolio_verdict",
        "format_version",
    ):
        if key in metadata:
            rows.append((key, _safe_text(metadata.get(key))))
    return rows


def _bucket_rows(data: dict[str, Any]) -> list[tuple[str, int]]:
    """Rows for the launch-buckets section, in canonical bucket order."""
    buckets = data.get("buckets")
    if not isinstance(buckets, dict):
        return [(bucket, 0) for bucket in BUCKET_ORDER]
    rows: list[tuple[str, int]] = []
    for bucket in BUCKET_ORDER:
        items = buckets.get(bucket)
        if isinstance(items, list):
            count = sum(
                1 for item in _as_list(items) if isinstance(item, dict)
            )
        else:
            count = 0
        rows.append((bucket, count))
    return rows


def _project_key(value: Any) -> int | None:
    """Normalise a project id to a hashable int key (or ``None``)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _ranked_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect ranked project items in digest order.

    Bucket lists are capped per bucket, so the export also honours the
    ``launch_sequence`` ids (which can include projects beyond a single
    bucket's cap) and then appends any remaining bucket rows that the
    sequence did not mention — sorted by their digest ``rank`` so the
    spreadsheet never shows rank 27 before rank 26 just because a later
    bucket happened to list it first. A missing ``top_pick`` is used as
    a final fallback so a minimal hand-built payload still exports its
    one row.
    """
    buckets = data.get("buckets")
    by_id: dict[int, dict[str, Any]] = {}
    if isinstance(buckets, dict):
        for bucket in BUCKET_ORDER:
            for item in _as_list(buckets.get(bucket)):
                if not isinstance(item, dict):
                    continue
                project_id = _project_key(item.get("project_id"))
                if project_id is not None and project_id not in by_id:
                    by_id[project_id] = item

    ordered: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_project_id in _as_list(data.get("launch_sequence")):
        project_id = _project_key(raw_project_id)
        if project_id in by_id and project_id not in seen:
            ordered.append(by_id[project_id])
            seen.add(project_id)

    remaining: list[dict[str, Any]] = []
    if isinstance(buckets, dict):
        for bucket in BUCKET_ORDER:
            for item in _as_list(buckets.get(bucket)):
                if not isinstance(item, dict):
                    continue
                project_id = _project_key(item.get("project_id"))
                if project_id is not None and project_id not in seen:
                    remaining.append(item)
                    seen.add(project_id)
    ordered.extend(sorted(remaining, key=_rank_order_key))

    top_pick = data.get("top_pick")
    top_pick_key = _project_key(
        top_pick.get("project_id") if isinstance(top_pick, dict) else None
    )
    if (
        isinstance(top_pick, dict)
        and top_pick_key is not None
        and top_pick_key not in seen
    ):
        ordered.append(top_pick)
    return ordered


def _rank_order_key(item: dict[str, Any]) -> tuple[float, int]:
    """Sort key for bucket rows the launch sequence did not mention."""
    rank = _safe_float(item.get("rank"))
    if rank is None:
        rank = float("inf")
    return (rank, _project_key(item.get("project_id")) or 0)


def portfolio_launch_priority_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a portfolio launch-priority payload as a multi-section CSV.

    Args:
        payload: the dict returned by
            :func:`app.simulation.portfolio_launch_priority.build_portfolio_launch_priority`
            (or its Pydantic model).
        metadata: optional provenance rows rendered at the top of the
            file (e.g. generated_at, user_id, format_version).
    """
    data = _as_dict(payload)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Portfolio Launch Priority Summary"])
    _write_row(writer, ["key", "value"])
    top_pick = data.get("top_pick")
    summary_rows: list[tuple[str, object]] = [
        ("project_count", data.get("project_count", 0)),
        ("evaluated_count", data.get("evaluated_count", 0)),
        ("portfolio_verdict", data.get("portfolio_verdict", "INSUFFICIENT_DATA")),
        (
            "top_pick_project_id",
            top_pick.get("project_id", "") if isinstance(top_pick, dict) else "",
        ),
        (
            "top_pick_project_title",
            top_pick.get("project_title", "") if isinstance(top_pick, dict) else "",
        ),
        ("next_focus", data.get("next_focus", "")),
        ("narrative", data.get("narrative", "")),
    ]
    for key, value in summary_rows:
        _write_row(writer, [key, value])
    _write_row(writer, [])

    # Launch buckets.
    _write_row(writer, ["section", "Launch Buckets"])
    _write_row(writer, ["bucket", "rows_in_digest"])
    for bucket, count in _bucket_rows(data):
        _write_row(writer, [bucket, count])
    _write_row(writer, [])

    # Launch sequence.
    _write_row(writer, ["section", "Launch Sequence"])
    _write_row(
        writer,
        [
            "rank",
            "project_id",
            "project_title",
            "bucket",
            "go_no_go_score",
            "verdict",
            "verdict_label",
            "latest_simulation_id",
            "latest_simulation_at",
            "has_outcomes",
            "top_action",
            "reason",
            "weakest_pillar_key",
            "weakest_pillar_label",
            "weakest_pillar_score",
        ],
    )
    for item in _ranked_items(data):
        weakest = item.get("weakest_pillar")
        weakest_pillar = weakest if isinstance(weakest, dict) else {}
        score = _safe_float(weakest_pillar.get("score"))
        _write_row(
            writer,
            [
                item.get("rank", ""),
                item.get("project_id", ""),
                item.get("project_title", ""),
                item.get("bucket", ""),
                _score_text(item.get("go_no_go_score")),
                item.get("verdict", ""),
                item.get("verdict_label", ""),
                item.get("latest_simulation_id", ""),
                item.get("latest_simulation_at", ""),
                item.get("has_outcomes", ""),
                item.get("top_action", ""),
                item.get("reason", ""),
                weakest_pillar.get("key", ""),
                weakest_pillar.get("label", ""),
                _score_text(score),
            ],
        )

    return buffer.getvalue()


__all__ = ["portfolio_launch_priority_to_csv"]

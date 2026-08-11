"""CSV/JSON export helpers for the project go/no-go launch scorecard.

The route layer in ``app/api/v1/projects.py`` already builds the go/no-go
payload with :func:`build_go_no_go`; this module renders that same payload
for download so founders can bring the launch verdict, pillar scores,
launch gates, strengths, risks and top actions into a planning spreadsheet
or hand the raw JSON to a BI pipeline.

The CSV follows the same lightweight multi-section convention as the
risk-register and launch-checklist exports: an optional metadata block, a
one-row-per-key summary section, one row per pillar, one row per gate,
strength/risk/action lists and a meta section. Missing optional fields
render as blanks rather than crashing the export, and malformed legacy
payloads (dict- or tuple-shaped pillar/gate collections, non-string list
items) are normalised so summary counts always match the rows actually
rendered and no Python reprs leak into spreadsheet cells. The CSV starts
with a UTF-8 BOM so Excel decodes non-Latin pillar summaries and actions
correctly; the JSON export emits UTF-8 with ``ensure_ascii=False`` and a
trailing newline so the same text round-trips cleanly.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

FORMAT_VERSION: str = "1"

PILLAR_CSV_HEADERS: list[str] = [
    "key",
    "label",
    "score",
    "verdict",
    "weight",
    "summary",
    "evidence",
]

GATE_CSV_HEADERS: list[str] = [
    "id",
    "label",
    "evaluated",
    "passed",
    "detail",
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


def _value(value: Any) -> object:
    """Render one cell while preserving the original value's type."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    return value


def _safe_csv_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection while leaving data intact.

    Cells that begin with ``=``, ``+``, ``-``, ``@``, tab, or carriage return
    are prefixed with a single quote so Excel, LibreOffice, and Google Sheets
    treat them as literal text rather than executable formulas. The guard also
    catches formula characters hidden after leading whitespace, which Excel
    still interprets as formulas.
    """
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
        "project_id",
    ):
        value = metadata.get(key, "")
        rows.append((key, "" if value is None else str(value)))
    return rows


def _evidence_text(raw: Any) -> str:
    """Render a pillar's evidence list as a single CSV cell."""
    if isinstance(raw, (list, tuple)):
        return " | ".join(_safe_text(item) for item in raw)
    return _safe_text(raw)


def _list_rows(data: dict[str, Any], key: str) -> list[str]:
    """Normalise a string list field to a list of non-empty strings.

    Malformed items (dicts, nested lists, ``None``) are dropped rather
    than stringified, so a corrupt legacy payload cannot leak Python
    reprs into the spreadsheet.
    """
    raw = data.get(key) or []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    return [
        str(item)
        for item in raw
        if item is not None
        and not isinstance(item, (dict, list))
        and str(item) != ""
    ]


def _item_list(raw: Any) -> list[dict[str, Any]]:
    """Normalise a pillar/gate collection to renderable dicts.

    A malformed legacy payload (``None``, a string, or a dict instead of
    a list) degrades to an empty list, and unrenderable entries are
    dropped, so the summary counts always match the rows rendered.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    return [item for item in (_as_dict(entry) for entry in raw) if item]


def go_no_go_to_csv(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a go/no-go payload as a multi-section CSV string."""
    data = _as_dict(payload)
    pillars = _item_list(data.get("pillars"))
    gates = _item_list(data.get("gates"))
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    for key, value in _metadata_rows(metadata):
        _write_row(writer, [key, value])
    if metadata:
        _write_row(writer, [])

    # Summary section.
    _write_row(writer, ["section", "Go/No-Go Summary"])
    _write_row(writer, ["key", "value"])
    summary_keys = (
        "project_id",
        "latest_simulation_id",
        "go_no_go_score",
        "verdict",
        "verdict_label",
        "pillar_count",
        "gate_count",
        "strengths_count",
        "risks_count",
        "action_count",
        "narrative",
    )
    for key in summary_keys:
        if key == "pillar_count":
            value = len(pillars)
        elif key == "gate_count":
            value = len(gates)
        elif key == "strengths_count":
            value = len(_list_rows(data, "strengths"))
        elif key == "risks_count":
            value = len(_list_rows(data, "risks"))
        elif key == "action_count":
            value = len(_list_rows(data, "top_actions"))
        else:
            value = data.get(key)
        _write_row(writer, [key, _value(value)])
    _write_row(writer, [])

    # Pillar scores.
    _write_row(writer, ["section", "Pillars"])
    _write_row(writer, list(PILLAR_CSV_HEADERS))
    for pillar in pillars:
        _write_row(
            writer,
            [
                _value(pillar.get("key")),
                _value(pillar.get("label")),
                _value(pillar.get("score")),
                _value(pillar.get("verdict")),
                _value(pillar.get("weight")),
                _value(pillar.get("summary")),
                _evidence_text(pillar.get("evidence")),
            ],
        )
    _write_row(writer, [])

    # Launch gates.
    _write_row(writer, ["section", "Launch Gates"])
    _write_row(writer, list(GATE_CSV_HEADERS))
    for gate in gates:
        _write_row(
            writer,
            [
                _value(gate.get("id")),
                _value(gate.get("label")),
                _value(gate.get("evaluated")),
                _value(gate.get("passed")),
                _value(gate.get("detail")),
            ],
        )
    _write_row(writer, [])

    # Strengths / risks / top actions.
    _write_row(writer, ["section", "Strengths"])
    _write_row(writer, ["strength"])
    strengths = _list_rows(data, "strengths")
    if strengths:
        for strength in strengths:
            _write_row(writer, [strength])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    _write_row(writer, ["section", "Risks"])
    _write_row(writer, ["risk"])
    risks = _list_rows(data, "risks")
    if risks:
        for risk in risks:
            _write_row(writer, [risk])
    else:
        _write_row(writer, [""])
    _write_row(writer, [])

    _write_row(writer, ["section", "Top Actions"])
    _write_row(writer, ["rank", "action"])
    actions = _list_rows(data, "top_actions")
    if actions:
        for rank, action in enumerate(actions, start=1):
            _write_row(writer, [rank, action])
    else:
        _write_row(writer, ["", ""])
    _write_row(writer, [])

    # Meta section.
    _write_row(writer, ["section", "Meta"])
    _write_row(writer, ["key", "value"])
    meta = data.get("meta")
    if isinstance(meta, dict):
        for key in sorted(meta):
            _write_row(writer, [key, _value(meta[key])])
    else:
        _write_row(writer, ["", ""])

    # UTF-8 BOM: without it, Excel on Windows guesses ANSI and mangles
    # non-Latin pillar labels and narrative text even though the response
    # advertises charset=utf-8.
    return "\ufeff" + buffer.getvalue()


def go_no_go_to_json(
    payload: Any,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Render a go/no-go payload as an indented JSON document."""
    return json.dumps(
        {
            "metadata": metadata or {},
            "go_no_go": _as_dict(payload),
        },
        default=str,
        indent=2,
        ensure_ascii=False,
    ) + "\n"


__all__ = [
    "FORMAT_VERSION",
    "PILLAR_CSV_HEADERS",
    "GATE_CSV_HEADERS",
    "go_no_go_to_csv",
    "go_no_go_to_json",
]

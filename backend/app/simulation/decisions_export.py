"""
Pure helper for exporting a project's decisions as CSV.

The route layer pulls the decision rows and hands them here as dicts;
this module stays deterministic and treats missing/malformed fields as
empty strings.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def decisions_to_csv(decisions: list[dict[str, Any]]) -> str:
    """Render decision dicts as a single CSV table."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "project_id",
            "title",
            "status",
            "task_id",
            "result_json",
        ]
    )
    for decision in decisions:
        writer.writerow(
            [
                _text(decision.get("id")),
                _text(decision.get("project_id")),
                _text(decision.get("title")),
                _text(decision.get("status")),
                _text(decision.get("task_id")),
                _text(decision.get("result")),
            ]
        )
    return buffer.getvalue()


__all__ = ["decisions_to_csv"]

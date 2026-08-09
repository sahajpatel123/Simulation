"""Pure-helper tests for the portfolio launch-priority CSV export."""
from __future__ import annotations

import csv
import io

from app.simulation.portfolio_launch_priority_export import (
    portfolio_launch_priority_to_csv,
)


def _item(
    project_id: int,
    title: str,
    *,
    rank: int = 1,
    bucket: str = "LAUNCH_NOW",
    score: int | None = 80,
    verdict: str = "GO",
    weakest: dict | None = None,
    top_action: str = "",
    reason: str = "Signals support launch",
) -> dict:
    return {
        "rank": rank,
        "project_id": project_id,
        "project_title": title,
        "bucket": bucket,
        "go_no_go_score": score,
        "verdict": verdict,
        "verdict_label": verdict,
        "latest_simulation_id": project_id * 10,
        "latest_simulation_at": "2026-08-09T12:00:00+00:00",
        "has_outcomes": True,
        "top_action": top_action,
        "reason": reason,
        "weakest_pillar": weakest,
    }


def _rows_after_section(csv_text: str, section: str) -> list[list[str]]:
    """Return data rows immediately after a named section's header."""
    rows = list(csv.reader(io.StringIO(csv_text)))
    for index, row in enumerate(rows):
        if len(row) >= 2 and row[0] == "section" and row[1] == section:
            return rows[index + 2 :]
    return []


def test_empty_payload_renders_well_formed_csv() -> None:
    csv_text = portfolio_launch_priority_to_csv(
        {
            "project_count": 0,
            "evaluated_count": 0,
            "portfolio_verdict": "INSUFFICIENT_DATA",
            "top_pick": None,
            "buckets": {
                "LAUNCH_NOW": [],
                "CONDITIONAL_LAUNCH": [],
                "FIX_FIRST": [],
                "PARK": [],
            },
            "launch_sequence": [],
            "next_focus": "",
            "narrative": "No projects with a usable launch scorecard yet",
        },
        metadata={
            "generated_at": "2026-08-10T00:00:00+00:00",
            "user_id": 42,
            "project_count": 0,
            "evaluated_count": 0,
            "portfolio_verdict": "INSUFFICIENT_DATA",
            "format_version": "1",
        },
    )

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert ["generated_at", "2026-08-10T00:00:00+00:00"] in rows
    assert ["project_count", "0"] in rows
    assert ["section", "Portfolio Launch Priority Summary"] in rows
    assert ["section", "Launch Buckets"] in rows
    assert ["section", "Launch Sequence"] in rows
    assert _rows_after_section(csv_text, "Launch Sequence") == []


def test_ranked_rows_follow_launch_sequence_and_flatten_weakest_pillar() -> None:
    payload = {
        "project_count": 2,
        "evaluated_count": 2,
        "portfolio_verdict": "READY_TO_LAUNCH",
        "top_pick": _item(11, "Alpha"),
        "buckets": {
            "LAUNCH_NOW": [_item(11, "Alpha", rank=1)],
            "CONDITIONAL_LAUNCH": [
                _item(
                    22,
                    "Beta",
                    rank=2,
                    bucket="CONDITIONAL_LAUNCH",
                    score=70,
                    verdict="CONDITIONAL_GO",
                    weakest={
                        "key": "premortem",
                        "label": "Premortem",
                        "score": 33,
                    },
                )
            ],
            "FIX_FIRST": [],
            "PARK": [],
        },
        "launch_sequence": [11, 22],
        "next_focus": "Resolve the recurring premortem failure modes",
        "narrative": "2 project(s) evaluated",
    }

    csv_text = portfolio_launch_priority_to_csv(payload)
    rows = _rows_after_section(csv_text, "Launch Sequence")

    assert rows[0][:4] == ["1", "11", "Alpha", "LAUNCH_NOW"]
    assert rows[0][4] == "80"
    assert rows[1][:4] == ["2", "22", "Beta", "CONDITIONAL_LAUNCH"]
    assert rows[1][4] == "70"
    assert rows[1][-3:] == ["premortem", "Premortem", "33"]


def test_csv_escapes_cells_and_guards_formula_injection() -> None:
    payload = {
        "project_count": 1,
        "evaluated_count": 1,
        "portfolio_verdict": "READY_TO_LAUNCH",
        "top_pick": _item(
            7,
            "Alpha, Inc",
            top_action="=HYPERLINK(\"https://example.com\",\"Go\")",
            reason="Line one\nLine two",
        ),
        "buckets": {
            "LAUNCH_NOW": [
                _item(
                    7,
                    "Alpha, Inc",
                    top_action="=HYPERLINK(\"https://example.com\",\"Go\")",
                    reason="Line one\nLine two",
                )
            ],
            "CONDITIONAL_LAUNCH": [],
            "FIX_FIRST": [],
            "PARK": [],
        },
        "launch_sequence": [7],
        "next_focus": "",
        "narrative": "",
    }

    csv_text = portfolio_launch_priority_to_csv(payload)
    rows = list(csv.reader(io.StringIO(csv_text)))
    sequence_row = next(
        row for row in rows if len(row) > 11 and row[1] == "7"
    )

    assert sequence_row[2] == "Alpha, Inc"
    assert sequence_row[10].startswith("'=")
    assert sequence_row[11] == "Line one\nLine two"


def test_malformed_payload_degrades_to_empty_csv() -> None:
    csv_text = portfolio_launch_priority_to_csv(
        {
            "project_count": 1,
            "evaluated_count": 1,
            "portfolio_verdict": "INSUFFICIENT_DATA",
            "top_pick": [1, 2],
            "buckets": {
                "LAUNCH_NOW": [{"project_id": ["unhashable"]}],
                "CONDITIONAL_LAUNCH": [],
                "FIX_FIRST": [],
                "PARK": [],
            },
            "launch_sequence": "not-a-list",
        }
    )

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows
    assert ["section", "Portfolio Launch Priority Summary"] in rows
    assert ["section", "Launch Sequence"] in rows
    assert _rows_after_section(csv_text, "Launch Sequence") == []

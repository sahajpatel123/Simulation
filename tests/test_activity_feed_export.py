"""Tests for the pure activity-feed export helper."""
from __future__ import annotations

from app.simulation.activity_feed_export import activity_feed_to_csv


def test_activity_feed_to_csv_contains_header_and_rows() -> None:
    csv_text = activity_feed_to_csv(
        [
            {
                "type": "sim_completed",
                "occurred_at": "2026-01-02T00:00:00Z",
                "ref_id": 7,
                "title": "Simulation #7 completed",
                "summary": "Predicted 4.20% conversion",
                "severity": "ok",
            },
            {
                "type": "outcome_submitted",
                "occurred_at": "2026-01-03T00:00:00Z",
                "ref_id": 9,
                "title": "Outcome recorded",
                "summary": "Actual: 5.20% conversion",
                "severity": "ok",
            },
        ],
        metadata={
            "generated_at": "now",
            "project_id": 10,
            "user_id": 42,
        },
    )

    assert "type,occurred_at,ref_id,title,summary,severity" in csv_text
    assert "sim_completed,2026-01-02T00:00:00Z,7" in csv_text
    assert "outcome_submitted,2026-01-03T00:00:00Z,9" in csv_text
    assert "project_id,10" in csv_text
    assert "user_id,42" in csv_text


def test_activity_feed_to_csv_empty_events_still_has_header() -> None:
    csv_text = activity_feed_to_csv([])
    assert "type,occurred_at,ref_id,title,summary,severity" in csv_text


def test_activity_feed_to_csv_neutralizes_spreadsheet_formula_injection() -> None:
    csv_text = activity_feed_to_csv(
        [
            {
                "type": "decision_completed",
                "occurred_at": "=NOW()",
                "ref_id": 7,
                "title": "=HYPERLINK(\"http://evil\")",
                "summary": "-2+3",
                "severity": "@cmd",
            }
        ],
        metadata={
            "generated_at": "=NOW()",
            "project_id": 10,
            "user_id": 42,
            "format_version": "1",
        },
    )

    assert "'=NOW()" in csv_text
    assert "'=HYPERLINK" in csv_text
    assert "'-2+3" in csv_text
    assert "'@cmd" in csv_text


def test_activity_feed_to_csv_neutralizes_formula_after_leading_whitespace() -> None:
    csv_text = activity_feed_to_csv(
        [
            {
                "type": "sim_completed",
                "occurred_at": "2026-01-02T00:00:00Z",
                "ref_id": 1,
                "title": " =SUM(A1:A2)",
                "summary": "\t=CMD",
                "severity": " @cmd",
            }
        ]
    )

    assert "' =SUM(A1:A2)" in csv_text
    assert "'\t=CMD" in csv_text
    assert "' @cmd" in csv_text

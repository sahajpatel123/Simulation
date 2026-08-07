"""Tests for the pure evidence-export helper."""
from __future__ import annotations

from app.simulation.evidence_export import evidence_to_csv


def test_evidence_to_csv_contains_header_and_rows() -> None:
    csv_text = evidence_to_csv(
        [
            {
                "id": 1,
                "project_id": 10,
                "assumption_id": 3,
                "method": "interview",
                "result": "PASS",
                "observed_metric": 0.62,
                "notes": "validated",
                "created_at": "2026-08-07T20:00:00+00:00",
            }
        ],
        metadata={"generated_at": "now", "user_id": 42},
    )

    assert "id,project_id,assumption_id,method,result" in csv_text
    assert "1,10,3,interview,PASS,0.62,validated" in csv_text
    assert "generated_at,now" in csv_text


def test_evidence_to_csv_handles_missing_fields() -> None:
    csv_text = evidence_to_csv([{"id": 2}])

    assert "2,,," in csv_text

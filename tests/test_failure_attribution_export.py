"""Tests for the failure-attribution CSV/JSON export helpers."""

from __future__ import annotations

import csv
import io
import json

from app.simulation.failure_attribution_export import (
    FORMAT_VERSION,
    failure_attribution_to_csv,
    failure_attribution_to_json,
)


def _payload() -> dict:
    return {
        "project_id": 10,
        "total_outcomes": 3,
        "attributed_count": 2,
        "unattributed_count": 1,
        "top_reason": "PRICING",
        "reasons": [
            {
                "reason": "PRICING",
                "count": 2,
                "share_pct": 100.0,
                "avg_abs_variance_pp": 3.0,
                "avg_signed_variance_pp": -3.0,
                "avg_signal_quality": 0.6,
                "avg_learning_weight": 0.36,
                "avg_days_since_launch": 30.0,
                "data_confidence_breakdown": {
                    "EXACT": 1,
                    "ESTIMATED": 1,
                },
                "product_changed_count": 1,
                "pricing_changed_count": 2,
                "target_market_changed_count": 0,
                "severity": "watch",
            }
        ],
        "narrative": "Across 3 recorded outcome(s), 2 included a failure reason.",
        "key_signals": [],
    }


def test_csv_renders_metadata_summary_and_reason_rows() -> None:
    csv_text = failure_attribution_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-11T12:00:00+00:00",
            "user_id": 42,
            "project_id": 10,
            "format_version": FORMAT_VERSION,
        },
    )

    assert csv_text.startswith("generated_at,2026-08-11T12:00:00+00:00")
    assert "user_id,42" in csv_text
    assert "project_id,10" in csv_text
    assert "format_version,1" in csv_text
    assert "section,Summary" in csv_text
    assert "total_outcomes,3" in csv_text
    assert "attributed_count,2" in csv_text
    assert "unattributed_count,1" in csv_text
    assert "top_reason,PRICING" in csv_text
    assert "section,Reasons" in csv_text
    assert "PRICING,2,100.0,3.0,-3.0,0.6,0.36,30.0,1,2,0,watch" in csv_text


def test_csv_handles_empty_payload_without_crashing() -> None:
    csv_text = failure_attribution_to_csv(
        {
            "project_id": 10,
            "total_outcomes": 0,
            "attributed_count": 0,
            "unattributed_count": 0,
            "top_reason": None,
            "reasons": [],
            "narrative": "No outcomes yet.",
            "key_signals": [],
        }
    )

    parsed = list(csv.reader(io.StringIO(csv_text)))
    assert ["section", "Summary"] in parsed
    assert ["top_reason", ""] in parsed
    assert ["section", "Reasons"] in parsed


def test_csv_guards_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["top_reason"] = "=HYPERLINK(evil)"
    payload["reasons"][0]["reason"] = "+SUM(1,1)"
    payload["reasons"][0]["narrative"] = ""

    csv_text = failure_attribution_to_csv(payload)

    assert "'=HYPERLINK(evil)" in csv_text
    assert "'+SUM(1,1)" in csv_text


def test_json_envelope_contains_payload_and_metadata() -> None:
    text = failure_attribution_to_json(
        _payload(),
        metadata={
            "generated_at": "2026-08-11T12:00:00+00:00",
            "user_id": 42,
            "project_id": 10,
            "format_version": FORMAT_VERSION,
        },
    )

    parsed = json.loads(text)
    assert parsed["metadata"]["project_id"] == 10
    assert parsed["failure_attribution"]["top_reason"] == "PRICING"
    assert parsed["failure_attribution"]["reasons"][0]["count"] == 2

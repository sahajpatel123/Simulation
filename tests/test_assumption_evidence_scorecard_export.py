"""Pure-helper tests for the evidence-scorecard CSV/JSON/Markdown export.

Covers formula-injection guards, summary rendering, evidence-table rows,
unicode preservation, empty-state handling, and that all three formats
round-trip the same payload.
"""
from __future__ import annotations

import json

from app.simulation.evidence_scorecard_export import (
    FORMAT_VERSION,
    evidence_scorecard_to_csv,
    evidence_scorecard_to_json,
    evidence_scorecard_to_markdown,
)

_METADATA = {
    "generated_at": "2026-08-11T12:00:00+00:00",
    "user_id": 42,
    "format_version": FORMAT_VERSION,
    "assumption_id": 100,
    "project_id": 10,
}


def _payload(*, with_history: bool = True, unicode_text: bool = False) -> dict:
    assumption_text = "⚠️ 高风险" if unicode_text else "pricing claim"
    return {
        "project_id": 10,
        "assumption_id": 100,
        "assumption_text": assumption_text,
        "category": "PricingArchitect",
        "sensitivity": "CRITICAL",
        "evidence_count": 1,
        "latest_result": "PASS",
        "derived_confidence": "VALIDATED_INTERNAL",
        "confidence_before": "ASPIRATIONAL",
        "confidence_after": "VALIDATED_INTERNAL",
        "validation_roi_before": 0.75,
        "validation_roi_after": 0.45,
        "roi_tier_before": "HIGH_VALUE",
        "roi_tier_after": "VALIDATE_FIRST",
        "roi_delta": -0.30,
        "tier_upgraded": True,
        "recommendation": "PASS confirmed — upgrade confidence.",
        "history": [
            {
                "id": 1,
                "project_id": 10,
                "assumption_id": 100,
                "method": "WILLINGNESS_TO_PAY_SURVEY",
                "method_label": "Willingness-to-pay survey",
                "result": "PASS",
                "observed_metric": 0.42,
                "created_at": "2026-08-05T00:00:00+00:00",
                "derived_confidence": "VALIDATED_INTERNAL",
                "notes": "35 responses",
            }
        ] if with_history else [],
        "meta": {"model": "evidence_scorecard_v1"},
    }


# ── CSV ──────────────────────────────────────────────────────────────────


def test_csv_contains_metadata_block() -> None:
    csv_text = evidence_scorecard_to_csv(_payload(), metadata=_METADATA)

    assert "generated_at,2026-08-11T12:00:00+00:00" in csv_text
    assert "user_id,42" in csv_text
    assert "format_version,1" in csv_text
    assert "assumption_id,100" in csv_text


def test_csv_contains_summary_section() -> None:
    csv_text = evidence_scorecard_to_csv(_payload())

    assert "section,Evidence Scorecard Summary" in csv_text
    assert "section,Eividence Scorecard Summary" not in csv_text
    assert "assumption_text,pricing claim" in csv_text
    assert "validation_roi_before,0.75" in csv_text
    assert "validation_roi_after,0.45" in csv_text
    assert "tier_upgraded,yes" not in csv_text  # CSV renders raw bool
    assert "recommendation,PASS confirmed" in csv_text


def test_csv_renders_evidence_history_rows() -> None:
    csv_text = evidence_scorecard_to_csv(_payload())

    assert "section,Evidence History" in csv_text
    assert (
        "1,Willingness-to-pay survey,PASS,0.42,"
        "2026-08-05T00:00:00+00:00,VALIDATED_INTERNAL,35 responses" in csv_text
    )


def test_csv_starts_with_utf8_bom() -> None:
    csv_text = evidence_scorecard_to_csv(_payload(unicode_text=True))

    assert csv_text.startswith("﻿")
    assert "⚠️ 高风险" in csv_text


def test_csv_neutralizes_formula_injection() -> None:
    payload = _payload()
    payload["assumption_text"] = "=HYPERLINK(\"http://evil\")"
    csv_text = evidence_scorecard_to_csv(payload)

    assert "'=HYPERLINK(" in csv_text


def test_csv_empty_history_renders_blank_rows() -> None:
    csv_text = evidence_scorecard_to_csv(_payload(with_history=False))

    assert "section,Evidence History" in csv_text
    # Should have the header row but no data rows
    assert "Willingness-to-pay survey" not in csv_text


def test_csv_round_trips_with_json_model() -> None:
    """CSV and JSON must agree on the same payload."""
    payload = _payload()

    csv_text = evidence_scorecard_to_csv(payload)
    json_text = evidence_scorecard_to_json(payload)

    json_data = json.loads(json_text)
    scorecard = json_data["evidence_scorecard"]
    assert scorecard["assumption_text"] == "pricing claim"
    assert "pricing claim" in csv_text


# ── JSON ─────────────────────────────────────────────────────────────────


def test_json_envelope_has_metadata_and_scorecard() -> None:
    json_text = evidence_scorecard_to_json(_payload(), metadata=_METADATA)
    parsed = json.loads(json_text)

    assert parsed["metadata"]["user_id"] == 42
    assert parsed["metadata"]["format_version"] == "1"
    scorecard = parsed["evidence_scorecard"]
    assert scorecard["assumption_id"] == 100
    assert scorecard["validation_roi_before"] == 0.75
    assert scorecard["validation_roi_after"] == 0.45
    assert len(scorecard["history"]) == 1
    assert scorecard["history"][0]["method_label"] == "Willingness-to-pay survey"


def test_json_preserves_unicode_and_trailing_newline() -> None:
    json_text = evidence_scorecard_to_json(_payload(unicode_text=True))

    assert json_text.endswith("\n")
    assert "⚠️ 高风险" in json_text
    json.loads(json_text)  # must not raise


def test_json_handles_none_values() -> None:
    payload = _payload()
    payload["latest_result"] = None
    payload["derived_confidence"] = None
    json_text = evidence_scorecard_to_json(payload)

    parsed = json.loads(json_text)
    assert parsed["evidence_scorecard"]["latest_result"] is None
    assert parsed["evidence_scorecard"]["derived_confidence"] is None


# ── Markdown ─────────────────────────────────────────────────────────────


def test_markdown_renders_assumption_header() -> None:
    md = evidence_scorecard_to_markdown(_payload())

    assert md.startswith("# Evidence Scorecard")
    assert "## Assumption: pricing claim" in md


def test_markdown_summary_table_formats_pct() -> None:
    md = evidence_scorecard_to_markdown(_payload())

    assert "## Summary" in md
    assert "| Field | Value |" in md
    assert "| Validation ROI (before) | 75.0% |" in md
    assert "| Validation ROI (after) | 45.0% |" in md
    assert "| Tier upgraded | yes |" in md


def test_markdown_renders_evidence_history_table() -> None:
    md = evidence_scorecard_to_markdown(_payload())

    assert "## Evidence History" in md
    assert "| # | Method | Result | Observed | Created | Confidence | Notes |" in md
    assert "Willingness-to-pay survey" in md
    assert "2026-08-05" in md


def test_markdown_renders_recommendation() -> None:
    md = evidence_scorecard_to_markdown(_payload())

    assert "## Recommendation" in md
    assert "PASS confirmed — upgrade confidence." in md


def test_markdown_empty_history_renders_gentle_message() -> None:
    md = evidence_scorecard_to_markdown(_payload(with_history=False))

    assert "No validation experiments logged yet." in md


def test_markdown_escapes_pipe_in_text() -> None:
    payload = _payload()
    payload["assumption_text"] = "price | cost | value"
    md = evidence_scorecard_to_markdown(payload)

    assert "price \\| cost \\| value" in md


def test_markdown_preserves_unicode() -> None:
    md = evidence_scorecard_to_markdown(_payload(unicode_text=True))

    assert "⚠️ 高风险" in md


def test_markdown_no_recommendation_omits_section() -> None:
    payload = _payload()
    payload["recommendation"] = ""
    md = evidence_scorecard_to_markdown(payload)

    assert "## Recommendation" not in md


def test_markdown_no_category_uses_dash() -> None:
    payload = _payload()
    payload["category"] = None
    md = evidence_scorecard_to_markdown(payload)

    # Category should render as — when None
    assert "| Category | — |" in md or "| Category |  |" in md


def test_markdown_round_trips_with_dumped_model() -> None:
    from app.schemas.assumption_evidence import AssumptionEvidenceScorecardOut

    model = AssumptionEvidenceScorecardOut(**_payload())
    md_from_dict = evidence_scorecard_to_markdown(model.model_dump())
    md_from_model = evidence_scorecard_to_markdown(model)

    assert md_from_dict == md_from_model

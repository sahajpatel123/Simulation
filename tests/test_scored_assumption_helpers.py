"""Focused tests for ``app.simulation.scored_assumption`` confidence + tier helpers.

The full scorer (score_assumptions) is exercised in integration tests; this file
locks down the pure helpers so future refactors don't silently regress the
priority order or signal-quality tier boundaries.
"""
from __future__ import annotations

from app.simulation.scored_assumption import (
    ClaimConfidence,
    classify_confidence,
    compute_signal_quality,
    signal_quality_tier,
)


def test_classify_confidence_validated_external() -> None:
    assert classify_confidence("Market research confirms a $5B TAM") is ClaimConfidence.VALIDATED_EXTERNAL


def test_classify_confidence_validated_internal() -> None:
    assert classify_confidence("Our pilot returned 45% week-2 retention") is ClaimConfidence.VALIDATED_INTERNAL


def test_classify_confidence_aspirational() -> None:
    assert classify_confidence("We hope to reach tier-1 by next year") is ClaimConfidence.ASPIRATIONAL


def test_classify_confidence_default_design_intent() -> None:
    assert classify_confidence("Onboarding is a 3-step form") is ClaimConfidence.DESIGN_INTENT


def test_classify_confidence_priority_order() -> None:
    """External validation outranks internal which outranks aspirational."""
    mixed = "Market research showed growth and we hope to keep it up"
    assert classify_confidence(mixed) is ClaimConfidence.VALIDATED_EXTERNAL


def test_classify_confidence_is_case_insensitive() -> None:
    assert classify_confidence("MARKET RESEARCH confirms $5B TAM") is ClaimConfidence.VALIDATED_EXTERNAL


def test_signal_quality_tier_full() -> None:
    assert signal_quality_tier(0.50) == "FULL"
    assert signal_quality_tier(0.85) == "FULL"


def test_signal_quality_tier_partial() -> None:
    assert signal_quality_tier(0.25) == "PARTIAL"
    assert signal_quality_tier(0.49) == "PARTIAL"


def test_signal_quality_tier_quarantined() -> None:
    assert signal_quality_tier(0.24) == "QUARANTINED"
    assert signal_quality_tier(0.0) == "QUARANTINED"


def test_compute_signal_quality_empty_assumptions() -> None:
    assert compute_signal_quality([], hard_contradiction_count=0) == 0.0


def test_compute_signal_quality_caps_at_one() -> None:
    class _Scored:
        claim_confidence = ClaimConfidence.VALIDATED_EXTERNAL
        specificity_score = 1.0

    score = compute_signal_quality([_Scored(), _Scored()], hard_contradiction_count=0)
    assert 0.0 <= score <= 1.0


def test_compute_signal_quality_clamps_to_zero_with_contradictions() -> None:
    class _Scored:
        claim_confidence = ClaimConfidence.DESIGN_INTENT
        specificity_score = 0.0

    score = compute_signal_quality([_Scored()], hard_contradiction_count=10)
    assert score == 0.0

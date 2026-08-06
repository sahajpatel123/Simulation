"""
Tests for the de-risking scorecard engine (evidence → confidence → ROI shift).

The engine turns logged experiment results (PASS / FAIL / INCONCLUSIVE) into
an evidence-derived confidence tier and recomputes the validation-ROI formula
``sensitivity x (1 - confidence)`` to show how de-risking priority shifts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from app.schemas.assumption_evidence import (
    AssumptionEvidenceScorecardOut,
    EvidenceOut,
)
from app.simulation.evidence_scorecard import (
    EVIDENCE_RESULT_FAIL,
    EVIDENCE_RESULT_INCONCLUSIVE,
    EVIDENCE_RESULT_PASS,
    build_assumption_scorecard,
    derive_confidence,
    evidence_to_out,
)
from app.simulation.scored_assumption import ClaimConfidence


ENV: dict[str, Any] = {
    "price_sensitivity": 0.5,
    "market_maturity": 0.3,
    "average_order_value": 999.0,
}

BASE_RESULTS: dict[str, Any] = {
    "population_weighted_conversion": 0.05,
    "mean_conversion_rate": 0.05,
    "mean_revenue": 999.0,
    "total_agents": 10000,
    "converted": 500,
    "product_type_detected": "saas",
}

# Same assumption fixtures as test_validation_roi.py — each triggers a
# Markov keyword rule so the sensitivity engine yields a non-zero swing.
ASSUMPTIONS: list[dict[str, Any]] = [
    {
        "text": "We believe pricing will be 999 rupees per month for this",
        "sensitivity": "CRITICAL",
        "impact_score": 9.0,
        "category": "PricingArchitect",
    },
    {
        "text": "Market research shows strong market demand for this solution",
        "sensitivity": "CRITICAL",
        "impact_score": 9.0,
        "category": "MarketSizeArchitect",
    },
    {
        "text": "We ran an A/B test and pricing converts well",
        "sensitivity": "HIGH",
        "impact_score": 7.0,
        "category": "CustomerAcquisitionArchitect",
    },
    {
        "text": "The product has no real competitors",
        "sensitivity": "MEDIUM",
        "impact_score": 6.0,
        "category": "CompetitiveDynamicsArchitect",
    },
]


def _ts(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _evidence(
    *,
    eid: int,
    method: str = "WILLINGNESS_TO_PAY_SURVEY",
    result: str = EVIDENCE_RESULT_PASS,
    day: int = 5,
    metric: float | None = 0.42,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid,
        project_id=2,
        assumption_id=1,
        method=method,
        result=result,
        observed_metric=metric,
        notes="35 responses, 14 would pay",
        created_at=_ts(day),
    )


def _assumption(text: str = ASSUMPTIONS[0]["text"]) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        text=text,
        category="PricingArchitect",
        sensitivity="CRITICAL",
    )


def _build(
    *,
    assumption: Any | None = None,
    evidence: list[Any] | None = None,
    assumptions: list[Any] | None = None,
) -> AssumptionEvidenceScorecardOut:
    return build_assumption_scorecard(
        simulation_id=1,
        project_id=2,
        assumption=assumption if assumption is not None else _assumption(),
        evidence=evidence or [],
        base_results=BASE_RESULTS,
        env_params=ENV,
        existing_assumptions=assumptions if assumptions is not None else ASSUMPTIONS,
        signal_quality=0.62,
    )


class TestDeriveConfidence:
    def test_pass_upgrades_to_internal(self) -> None:
        assert derive_confidence(EVIDENCE_RESULT_PASS) == (
            ClaimConfidence.VALIDATED_INTERNAL
        )

    def test_fail_drops_to_aspirational(self) -> None:
        assert derive_confidence(EVIDENCE_RESULT_FAIL) == ClaimConfidence.ASPIRATIONAL

    def test_inconclusive_is_neutral(self) -> None:
        assert derive_confidence(EVIDENCE_RESULT_INCONCLUSIVE) is None


class TestEvidenceToOut:
    def test_method_label_and_derived_confidence(self) -> None:
        out = evidence_to_out(
            _evidence(eid=7, method="LANDING_PAGE_SMOKE_TEST"), "some claim"
        )
        assert isinstance(out, EvidenceOut)
        assert out.id == 7
        assert out.assumption_text == "some claim"
        assert out.method_label == "Landing-page smoke test"
        assert out.derived_confidence == "VALIDATED_INTERNAL"


class TestScorecardNoEvidence:
    def test_zero_state(self) -> None:
        out = _build()
        assert out.evidence_count == 0
        assert out.latest_result is None
        assert out.derived_confidence is None
        assert out.validation_roi_before == out.validation_roi_after
        assert out.roi_delta == 0.0
        assert "validation-experiment plan" in out.recommendation
        assert out.meta["model"] == "evidence_scorecard_v1"


class TestScorecardPass:
    def test_pass_raises_confidence_and_lowers_roi(self) -> None:
        out = _build(evidence=[_evidence(eid=1, result=EVIDENCE_RESULT_PASS)])
        assert out.evidence_count == 1
        assert out.derived_confidence == "VALIDATED_INTERNAL"
        assert out.confidence_after == "VALIDATED_INTERNAL"
        assert out.validation_roi_after is not None
        assert out.validation_roi_before is not None
        assert out.validation_roi_after < out.validation_roi_before
        assert out.roi_delta < 0.0
        assert "PASS" in out.recommendation

    def test_pass_never_downgrades_external_evidence(self) -> None:
        market = "Market research shows strong market demand for this solution"
        out = _build(
            assumption=_assumption(market),
            evidence=[_evidence(eid=2, result=EVIDENCE_RESULT_PASS)],
        )
        assert out.confidence_before == "VALIDATED_EXTERNAL"
        assert out.confidence_after == "VALIDATED_EXTERNAL"
        assert out.validation_roi_after == out.validation_roi_before
        assert out.roi_delta == 0.0


class TestScorecardFail:
    def test_fail_downgrades_confidence_and_raises_roi(self) -> None:
        ab_test = "We ran an A/B test and pricing converts well"
        out = _build(
            assumption=_assumption(ab_test),
            evidence=[_evidence(eid=3, result=EVIDENCE_RESULT_FAIL, metric=0.02)],
        )
        assert out.confidence_before == "VALIDATED_INTERNAL"
        assert out.derived_confidence == "ASPIRATIONAL"
        assert out.confidence_after == "ASPIRATIONAL"
        assert out.validation_roi_after is not None
        assert out.validation_roi_before is not None
        assert out.validation_roi_after > out.validation_roi_before
        assert out.roi_delta > 0.0
        assert "FAIL" in out.recommendation


class TestScorecardInconclusive:
    def test_inconclusive_is_no_op(self) -> None:
        out = _build(
            evidence=[
                _evidence(eid=4, result=EVIDENCE_RESULT_INCONCLUSIVE, day=3)
            ]
        )
        assert out.derived_confidence is None
        assert out.latest_result == EVIDENCE_RESULT_INCONCLUSIVE
        assert out.validation_roi_after == out.validation_roi_before
        assert out.roi_delta == 0.0
        assert "INCONCLUSIVE" in out.recommendation


class TestScorecardDecisivePolicy:
    def test_trailing_inconclusive_does_not_erase_earlier_pass(self) -> None:
        out = _build(
            evidence=[
                _evidence(eid=6, result=EVIDENCE_RESULT_PASS, day=2),
                _evidence(eid=7, result=EVIDENCE_RESULT_INCONCLUSIVE, day=4),
            ]
        )
        assert out.evidence_count == 2
        assert out.latest_result == EVIDENCE_RESULT_INCONCLUSIVE
        assert out.derived_confidence == "VALIDATED_INTERNAL"
        assert out.validation_roi_after < out.validation_roi_before

    def test_most_recent_decisive_wins(self) -> None:
        ab_test = "We ran an A/B test and pricing converts well"
        out = _build(
            assumption=_assumption(ab_test),
            evidence=[
                _evidence(eid=8, result=EVIDENCE_RESULT_PASS, day=2),
                _evidence(eid=9, result=EVIDENCE_RESULT_FAIL, day=4, metric=0.01),
            ]
        )
        assert out.derived_confidence == "ASPIRATIONAL"
        assert out.validation_roi_after > out.validation_roi_before


class TestScorecardHistoryOrder:
    def test_history_is_most_recent_first(self) -> None:
        out = _build(
            evidence=[
                _evidence(eid=10, result=EVIDENCE_RESULT_INCONCLUSIVE, day=1),
                _evidence(eid=11, result=EVIDENCE_RESULT_PASS, day=6),
            ]
        )
        assert [e.id for e in out.history] == [11, 10]

    def test_naive_and_aware_timestamps_sort_safely(self) -> None:
        naive = _evidence(eid=12, result=EVIDENCE_RESULT_PASS, day=2)
        naive.created_at = datetime(2026, 1, 2)  # naive — legacy DB row shape
        aware_later = _evidence(eid=13, result=EVIDENCE_RESULT_INCONCLUSIVE, day=6)
        out = _build(evidence=[naive, aware_later])
        assert [e.id for e in out.history] == [13, 12]


class TestResultNormalization:
    def test_lowercase_legacy_result_is_still_decisive(self) -> None:
        out = _build(
            evidence=[_evidence(eid=14, result="pass", day=4)],
        )
        assert out.derived_confidence == "VALIDATED_INTERNAL"
        assert out.confidence_after == "VALIDATED_INTERNAL"
        assert out.validation_roi_after is not None
        assert out.validation_roi_before is not None
        assert out.validation_roi_after < out.validation_roi_before
        assert "PASS" in out.recommendation

    def test_whitespace_padded_fail_is_still_decisive(self) -> None:
        ab_test = "We ran an A/B test and pricing converts well"
        out = _build(
            assumption=_assumption(ab_test),
            evidence=[_evidence(eid=15, result=" FAIL ", day=4, metric=0.01)],
        )
        assert out.derived_confidence == "ASPIRATIONAL"
        assert out.confidence_after == "ASPIRATIONAL"
        assert out.validation_roi_after is not None
        assert out.validation_roi_before is not None
        assert out.validation_roi_after > out.validation_roi_before
        assert "FAIL" in out.recommendation


class TestScorecardRecommendationAccuracy:
    def test_pass_on_external_evidence_reports_stable_confidence(self) -> None:
        market = "Market research shows strong market demand for this solution"
        out = _build(
            assumption=_assumption(market),
            evidence=[_evidence(eid=16, result=EVIDENCE_RESULT_PASS)],
        )
        assert out.confidence_before == "VALIDATED_EXTERNAL"
        assert out.confidence_after == "VALIDATED_EXTERNAL"
        assert out.validation_roi_after == out.validation_roi_before
        assert "stays VALIDATED_EXTERNAL" in out.recommendation
        assert "fell" not in out.recommendation

    def test_fail_on_aspirational_claim_does_not_claim_priority_rose(self) -> None:
        # "We believe..." heuristically starts ASPIRATIONAL, so a FAIL changes
        # nothing — the recommendation must not claim the priority rose.
        out = _build(
            evidence=[_evidence(eid=17, result=EVIDENCE_RESULT_FAIL, metric=0.01)],
        )
        assert out.confidence_before == "ASPIRATIONAL"
        assert out.confidence_after == "ASPIRATIONAL"
        assert out.validation_roi_after == out.validation_roi_before
        assert "FAIL" in out.recommendation
        assert "rose" not in out.recommendation

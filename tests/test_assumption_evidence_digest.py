"""Tests for the project-level validation-evidence digest.

The digest answers a portfolio question the per-assumption scorecard
leaves open: across every visible assumption, how much real-world
evidence exists, how many claims are de-risked or challenged, and what
should the founder run next.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.simulation.assumption_evidence_digest import (
    RESULT_OTHER,
    STATUS_CHALLENGED,
    STATUS_DE_RISKED,
    STATUS_INCONCLUSIVE,
    STATUS_PENDING,
    build_assumption_evidence_digest,
)
from app.simulation.evidence_scorecard import (
    EVIDENCE_RESULT_FAIL,
    EVIDENCE_RESULT_INCONCLUSIVE,
    EVIDENCE_RESULT_PASS,
)


def _ts(day: int) -> datetime:
    return datetime(2026, 2, day, tzinfo=UTC)


def _assumption(
    assumption_id: int,
    *,
    text: str = "Pricing will be 999 rupees per month",
    category: str = "PricingArchitect",
    sensitivity: str = "CRITICAL",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assumption_id,
        text=text,
        category=category,
        sensitivity=sensitivity,
    )


def _evidence(
    evidence_id: int,
    assumption_id: int,
    *,
    method: str = "WILLINGNESS_TO_PAY_SURVEY",
    result: str = EVIDENCE_RESULT_PASS,
    day: int = 5,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=evidence_id,
        project_id=1,
        assumption_id=assumption_id,
        method=method,
        result=result,
        created_at=_ts(day),
    )


class TestZeroState:
    def test_no_assumptions(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[],
            evidence=[],
            project_id=9,
        )
        assert out["project_id"] == 9
        assert out["total_assumptions"] == 0
        assert out["total_evidence_rows"] == 0
        assert out["evidence_coverage_pct"] is None
        assert out["validation_score"] is None
        assert out["next_action"].startswith("No visible assumptions")

    def test_assumptions_without_evidence(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[
                _assumption(1, sensitivity="CRITICAL"),
                _assumption(2, sensitivity="LOW"),
            ],
            evidence=[],
            project_id=9,
        )
        assert out["total_assumptions"] == 2
        assert out["total_evidence_rows"] == 0
        assert out["assumptions_with_evidence"] == 0
        assert out["evidence_coverage_pct"] == 0.0
        assert out["validation_score"] == 0.0
        assert out["pending_count"] == 2
        assert out["result_counts"] == {
            EVIDENCE_RESULT_PASS: 0,
            EVIDENCE_RESULT_FAIL: 0,
            EVIDENCE_RESULT_INCONCLUSIVE: 0,
        }
        assert out["method_counts"] == {}
        assert "validation-experiment plan" in out["next_action"]
        assert out["assumptions"][0]["assumption_id"] == 1


class TestMixedEvidence:
    def test_counts_and_histograms(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[
                _assumption(1, text="Pricing works", category="PricingArchitect"),
                _assumption(
                    2,
                    text="Demand is strong",
                    category="MarketSizeArchitect",
                    sensitivity="HIGH",
                ),
                _assumption(
                    3,
                    text="Users will adopt",
                    category="OnboardingArchitect",
                    sensitivity="MEDIUM",
                ),
                _assumption(
                    4,
                    text="No competitors",
                    category="CompetitiveDynamicsArchitect",
                    sensitivity="LOW",
                ),
            ],
            evidence=[
                _evidence(
                    1,
                    1,
                    method="WILLINGNESS_TO_PAY_SURVEY",
                    result=EVIDENCE_RESULT_PASS,
                    day=2,
                ),
                _evidence(
                    2,
                    2,
                    method="LANDING_PAGE_SMOKE_TEST",
                    result=EVIDENCE_RESULT_FAIL,
                    day=4,
                ),
                _evidence(
                    3,
                    3,
                    method="USER_INTERVIEWS",
                    result=EVIDENCE_RESULT_INCONCLUSIVE,
                    day=6,
                ),
            ],
            project_id=9,
        )
        assert out["total_evidence_rows"] == 3
        assert out["assumptions_with_evidence"] == 3
        assert out["evidence_coverage_pct"] == 0.75
        assert out["validation_score"] == 0.25
        assert out["de_risked_count"] == 1
        assert out["challenged_count"] == 1
        assert out["inconclusive_count"] == 1
        assert out["pending_count"] == 1
        assert out["result_counts"] == {
            EVIDENCE_RESULT_PASS: 1,
            EVIDENCE_RESULT_FAIL: 1,
            EVIDENCE_RESULT_INCONCLUSIVE: 1,
        }
        assert out["method_counts"] == {
            "WILLINGNESS_TO_PAY_SURVEY": 1,
            "LANDING_PAGE_SMOKE_TEST": 1,
            "USER_INTERVIEWS": 1,
        }
        by_id = {row["assumption_id"]: row for row in out["assumptions"]}
        assert by_id[1]["status"] == STATUS_DE_RISKED
        assert by_id[2]["status"] == STATUS_CHALLENGED
        assert by_id[3]["status"] == STATUS_INCONCLUSIVE
        assert by_id[4]["status"] == STATUS_PENDING
        assert by_id[1]["derived_confidence"] == "VALIDATED_INTERNAL"
        assert by_id[2]["derived_confidence"] == "ASPIRATIONAL"

    def test_next_action_prioritises_challenged(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(
                    1,
                    1,
                    result=EVIDENCE_RESULT_FAIL,
                    day=3,
                )
            ],
            project_id=9,
        )
        assert out["next_action"].startswith("Challenged assumption")


class TestDecisivePolicy:
    def test_trailing_inconclusive_does_not_erase_earlier_pass(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(
                    1,
                    1,
                    result=EVIDENCE_RESULT_PASS,
                    day=2,
                ),
                _evidence(
                    2,
                    1,
                    result=EVIDENCE_RESULT_INCONCLUSIVE,
                    day=4,
                ),
            ],
            project_id=9,
        )
        row = out["assumptions"][0]
        assert row["evidence_count"] == 2
        assert row["latest_result"] == EVIDENCE_RESULT_INCONCLUSIVE
        assert row["status"] == STATUS_DE_RISKED
        assert row["derived_confidence"] == "VALIDATED_INTERNAL"

    def test_most_recent_decisive_wins(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(
                    1,
                    1,
                    result=EVIDENCE_RESULT_PASS,
                    day=2,
                ),
                _evidence(
                    2,
                    1,
                    result=EVIDENCE_RESULT_FAIL,
                    day=5,
                ),
            ],
            project_id=9,
        )
        row = out["assumptions"][0]
        assert row["status"] == STATUS_CHALLENGED
        assert row["derived_confidence"] == "ASPIRATIONAL"


class TestTopLists:
    def test_pending_sorts_by_sensitivity(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[
                _assumption(10, sensitivity="LOW"),
                _assumption(11, sensitivity="CRITICAL"),
            ],
            evidence=[],
            project_id=9,
        )
        assert [row["assumption_id"] for row in out["top_pending"]] == [11, 10]

    def test_challenged_includes_most_relevant_first(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[
                _assumption(10, sensitivity="MEDIUM"),
                _assumption(11, sensitivity="CRITICAL"),
            ],
            evidence=[
                _evidence(
                    1,
                    10,
                    result=EVIDENCE_RESULT_FAIL,
                    day=2,
                ),
                _evidence(
                    2,
                    11,
                    result=EVIDENCE_RESULT_FAIL,
                    day=3,
                ),
            ],
            project_id=9,
        )
        assert [row["assumption_id"] for row in out["top_challenged"]] == [
            11,
            10,
        ]


class TestDefensiveRows:
    def test_unknown_results_still_count_as_rows(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(1, 1, result="MAYBE", day=2),
                _evidence(
                    2,
                    1,
                    result=EVIDENCE_RESULT_INCONCLUSIVE,
                    day=3,
                ),
            ],
            project_id=9,
        )
        assert out["total_evidence_rows"] == 2
        assert out["assumptions_with_evidence"] == 1
        assert out["result_counts"][EVIDENCE_RESULT_PASS] == 0
        assert out["result_counts"][EVIDENCE_RESULT_INCONCLUSIVE] == 1
        assert out["assumptions"][0]["status"] == STATUS_INCONCLUSIVE


class TestCanonicalisation:
    def test_legacy_result_and_method_casing_are_canonicalised(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(
                    1,
                    1,
                    method=" willingness_to_pay_survey ",
                    result=" pass ",
                    day=2,
                ),
            ],
            project_id=9,
        )
        row = out["assumptions"][0]
        assert row["latest_result"] == EVIDENCE_RESULT_PASS
        assert row["status"] == STATUS_DE_RISKED
        assert out["result_counts"][EVIDENCE_RESULT_PASS] == 1
        assert out["method_counts"] == {"WILLINGNESS_TO_PAY_SURVEY": 1}

    def test_unknown_result_buckets_into_other(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(1, 1, result="MAYBE", day=2),
                _evidence(
                    2,
                    1,
                    result=EVIDENCE_RESULT_INCONCLUSIVE,
                    day=3,
                ),
            ],
            project_id=9,
        )
        assert out["total_evidence_rows"] == 2
        assert out["result_counts"][RESULT_OTHER] == 1
        assert sum(out["result_counts"].values()) == out["total_evidence_rows"]

    def test_unknown_method_is_trimmed_but_not_renamed(self) -> None:
        out = build_assumption_evidence_digest(
            assumptions=[_assumption(1)],
            evidence=[
                _evidence(
                    1,
                    1,
                    method=" Mystery-method ",
                    result=EVIDENCE_RESULT_FAIL,
                    day=2,
                ),
            ],
            project_id=9,
        )
        assert out["method_counts"] == {"Mystery-method": 1}

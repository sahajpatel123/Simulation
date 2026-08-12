"""Tests for the assumption-validation timeline pure helper.

The helper replays logged evidence chronologically and computes cumulative
de-risking progress, so these tests focus on ordering, decisive-result
policy, milestone detection, orphan/hidden-row handling, and the
schema round-trip.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.schemas.validation_timeline import AssumptionValidationTimelineOut
from app.simulation.assumption_evidence_digest import (
    STATUS_CHALLENGED,
    STATUS_DE_RISKED,
    STATUS_INCONCLUSIVE,
    STATUS_PENDING,
)
from app.simulation.validation_timeline import build_validation_timeline


def _ts(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=UTC)


def _assumption(
    assumption_id: int,
    *,
    text: str = "Pricing will be 999 rupees per month",
    category: str = "PricingArchitect",
    sensitivity: str = "HIGH",
    is_hidden: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assumption_id,
        text=text,
        category=category,
        sensitivity=sensitivity,
        is_hidden=is_hidden,
    )


def _evidence(
    evidence_id: int,
    *,
    assumption_id: int = 1,
    result: str = "PASS",
    day: int = 1,
    method: str = "WILLINGNESS_TO_PAY_SURVEY",
    metric: float | None = 0.42,
    notes: str = "35 responses",
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=evidence_id,
        assumption_id=assumption_id,
        method=method,
        result=result,
        observed_metric=metric,
        notes=notes,
        created_at=created_at if created_at is not None else _ts(day),
    )


def _build(
    *,
    assumptions: list[Any] | None = None,
    evidence: list[Any] | None = None,
    project_id: int = 10,
) -> dict[str, Any]:
    return build_validation_timeline(
        assumptions=assumptions or [_assumption(1)],
        evidence=evidence or [],
        project_id=project_id,
    )


class TestEmptyTimeline:
    def test_zero_state(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[],
        )
        assert out["project_id"] == 10
        assert out["total_assumptions"] == 2
        assert out["total_evidence_rows"] == 0
        assert out["events"] == []
        assert out["progress"] == []
        assert out["milestones"]["first_evidence_event_id"] is None
        assert {row["status"] for row in out["assumptions"]} == {
            STATUS_PENDING
        }
        assert out["meta"]["model"] == "assumption_validation_timeline_v1"

    def test_hidden_and_orphan_evidence_are_excluded(self) -> None:
        out = _build(
            assumptions=[
                _assumption(1, is_hidden=True),
                _assumption(2),
            ],
            evidence=[
                _evidence(10, assumption_id=1),
                _evidence(11, assumption_id=999),
            ],
        )
        assert out["total_assumptions"] == 1
        assert out["total_evidence_rows"] == 0
        assert out["assumptions"][0]["status"] == STATUS_PENDING


class TestChronologicalOrder:
    def test_sorts_by_created_at_then_id(self) -> None:
        out = _build(
            evidence=[
                _evidence(20, result="INCONCLUSIVE", day=3),
                _evidence(10, result="PASS", day=1),
                _evidence(30, result="FAIL", day=2, metric=0.01),
            ],
        )
        assert [event["event_id"] for event in out["events"]] == [10, 30, 20]
        assert [snap["event_id"] for snap in out["progress"]] == [10, 30, 20]

    def test_naive_and_aware_timestamps_sort_safely(self) -> None:
        naive = _evidence(10, result="PASS", day=2)
        naive.created_at = datetime(2026, 1, 2)  # legacy naive timestamp
        aware = _evidence(20, result="FAIL", day=6, metric=0.01)
        out = _build(evidence=[naive, aware])
        assert [event["event_id"] for event in out["events"]] == [10, 20]


class TestStatusPolicy:
    def test_inconclusive_after_pass_keeps_de_risked(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(10, result="PASS", day=1),
                _evidence(11, result="INCONCLUSIVE", day=2),
            ],
        )
        assert [event["status_after"] for event in out["events"]] == [
            STATUS_DE_RISKED,
            STATUS_DE_RISKED,
        ]
        assert out["progress"][-1]["de_risked_count"] == 1
        assert out["progress"][-1]["inconclusive_count"] == 0
        assert out["progress"][-1]["pending_count"] == 1
        assert out["milestones"]["first_inconclusive_event_id"] is None

    def test_fail_after_pass_challenges_assumption(self) -> None:
        out = _build(
            evidence=[
                _evidence(10, result="PASS", day=1),
                _evidence(11, result="FAIL", day=2, metric=0.01),
            ],
        )
        assert [event["status_after"] for event in out["events"]] == [
            STATUS_DE_RISKED,
            STATUS_CHALLENGED,
        ]
        assert out["milestones"]["first_de_risked_event_id"] == 10
        assert out["milestones"]["first_challenged_event_id"] == 11
        assert out["milestones"]["first_evidence_event_id"] == 10
        assert out["milestones"]["last_evidence_event_id"] == 11
        assert out["progress"][-1]["de_risked_count"] == 0
        assert out["progress"][-1]["challenged_count"] == 1
        assert out["progress"][-1]["validation_score"] == 0.0

    def test_inconclusive_then_pass_sets_first_milestones(self) -> None:
        out = _build(
            evidence=[
                _evidence(10, result="INCONCLUSIVE", day=1),
                _evidence(11, result="PASS", day=2),
            ],
        )
        assert [event["status_after"] for event in out["events"]] == [
            STATUS_INCONCLUSIVE,
            STATUS_DE_RISKED,
        ]
        assert out["milestones"]["first_inconclusive_event_id"] == 10
        assert out["milestones"]["first_de_risked_event_id"] == 11

    def test_lowercase_legacy_decisive_still_counts(self) -> None:
        out = _build(
            evidence=[
                _evidence(10, result="pass", day=1),
                _evidence(11, result="MAYBE", day=2),
            ],
        )
        assert out["total_evidence_rows"] == 2
        assert out["events"][0]["derived_confidence"] == "VALIDATED_INTERNAL"
        assert out["events"][-1]["derived_confidence"] is None
        assert out["events"][-1]["status_after"] == STATUS_DE_RISKED


class TestPerAssumptionSummary:
    def test_summary_tracks_first_and_latest_events(self) -> None:
        out = _build(
            evidence=[
                _evidence(10, result="PASS", day=1),
                _evidence(11, result="INCONCLUSIVE", day=2),
                _evidence(12, result="FAIL", day=3, metric=0.01),
            ],
        )
        row = out["assumptions"][0]
        assert row["evidence_count"] == 3
        assert row["status"] == STATUS_CHALLENGED
        assert row["first_evidence_event_id"] == 10
        assert row["latest_evidence_event_id"] == 12
        assert row["first_de_risked_event_id"] == 10
        assert row["first_challenged_event_id"] == 12

    def test_multi_assumption_rollup_and_method_label(self) -> None:
        out = _build(
            assumptions=[
                _assumption(1),
                _assumption(2),
                _assumption(3),
            ],
            evidence=[
                _evidence(10, result="PASS", day=1),
                _evidence(11, assumption_id=2, result="INCONCLUSIVE", day=2),
            ],
        )
        assert out["events"][0]["method_label"] == "Willingness-to-pay survey"
        last = out["progress"][-1]
        assert last["assumptions_with_evidence"] == 2
        assert last["de_risked_count"] == 1
        assert last["inconclusive_count"] == 1
        assert last["pending_count"] == 1
        assert last["validation_score"] == round(1 / 3, 4)
        assert last["evidence_coverage_pct"] == round(2 / 3, 4)


class TestSchemaRoundTrip:
    def test_payload_round_trips_through_response_model(self) -> None:
        payload = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(10, result="PASS", day=1),
                _evidence(11, assumption_id=2, result="FAIL", day=2),
            ],
        )
        out = AssumptionValidationTimelineOut(**payload)
        assert out.total_assumptions == 2
        assert out.total_evidence_rows == 2
        assert len(out.events) == 2
        assert len(out.progress) == 2
        assert out.milestones.first_de_risked_event_id == 10
        assert out.milestones.first_challenged_event_id == 11

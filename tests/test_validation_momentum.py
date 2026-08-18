"""Tests for the validation-momentum forecast pure helper.

The momentum builder reuses the validation-timeline replay, so these tests
focus on the new surface: evidence cadence, recent-vs-overall trend,
first-evidence / first-de-risked velocities, projected horizons, and the
confidence/caveat rules that keep sparse histories honest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.schemas.validation_momentum import ValidationMomentumOut
from app.simulation.validation_momentum import (
    TREND_ACCELERATING,
    TREND_DECELERATING,
    TREND_INSUFFICIENT,
    TREND_NO_EVIDENCE,
    build_validation_momentum,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _day(day: int, hour: int = 12) -> datetime:
    return BASE + timedelta(days=day - 1, hours=hour)


def _assumption(
    assumption_id: int,
    *,
    is_hidden: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assumption_id,
        text=f"Assumption {assumption_id}",
        category="PricingArchitect",
        sensitivity="HIGH",
        is_hidden=is_hidden,
    )


def _evidence(
    evidence_id: int,
    *,
    assumption_id: int = 1,
    result: str = "PASS",
    day: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=evidence_id,
        project_id=10,
        assumption_id=assumption_id,
        method="WILLINGNESS_TO_PAY_SURVEY",
        result=result,
        observed_metric=0.42 if result == "PASS" else 0.02,
        notes="35 responses",
        created_at=_day(day),
    )


def _build(
    *,
    assumptions: list[Any] | None = None,
    evidence: list[Any] | None = None,
    target_de_risked_pct: float = 1.0,
    now: datetime | None = None,
    project_id: int = 10,
) -> dict[str, Any]:
    return build_validation_momentum(
        assumptions=assumptions or [_assumption(1)],
        evidence=evidence or [],
        project_id=project_id,
        target_de_risked_pct=target_de_risked_pct,
        now=now,
    )


class TestZeroState:
    def test_no_evidence_is_explicit(self) -> None:
        out = _build(assumptions=[_assumption(1), _assumption(2)])
        assert out["project_id"] == 10
        assert out["counts"]["total_assumptions"] == 2
        assert out["counts"]["total_evidence_rows"] == 0
        assert out["counts"]["pending_count"] == 2
        assert out["counts"]["evidence_coverage_pct"] == 0.0
        assert out["velocity"]["trend"] == TREND_NO_EVIDENCE
        assert out["velocity"]["first_evidence_at"] is None
        assert out["velocity"]["coverage_velocity_per_week"] is None
        assert out["forecast"]["weeks_to_full_coverage"] is None
        assert out["forecast"]["weeks_to_de_risked_target"] is None
        assert out["forecast"]["confident"] is False
        assert out["forecast"]["caveats"]
        assert any("No validation experiments" in i for i in out["insights"])

    def test_hidden_and_orphan_rows_are_excluded(self) -> None:
        out = _build(
            assumptions=[
                _assumption(1, is_hidden=True),
                _assumption(2),
                _assumption(3),
            ],
            evidence=[
                _evidence(10, assumption_id=1, day=1),
                _evidence(11, assumption_id=999, day=2),
                _evidence(12, assumption_id=2, day=3),
            ],
        )
        assert out["counts"]["total_assumptions"] == 2
        assert out["counts"]["total_evidence_rows"] == 1
        assert out["counts"]["assumptions_with_evidence"] == 1
        assert out["counts"]["de_risked_count"] == 1


class TestInsufficientHistory:
    def test_single_event_has_no_rates_or_horizon(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[_evidence(1, assumption_id=1, day=5)],
            now=_day(6),
        )
        assert out["velocity"]["trend"] == TREND_INSUFFICIENT
        assert out["velocity"]["overall_events_per_week"] is None
        assert out["velocity"]["coverage_velocity_per_week"] is None
        assert out["forecast"]["weeks_to_full_coverage"] is None
        assert out["forecast"]["confident"] is False

    def test_same_day_events_do_not_produce_weekly_rates(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(1, assumption_id=1, day=5, result="PASS"),
                _evidence(2, assumption_id=2, day=5, result="PASS"),
            ],
            now=_day(5, hour=18),
        )
        assert out["velocity"]["trend"] == TREND_INSUFFICIENT
        assert out["velocity"]["evidence_span_days"] == 0.0
        assert out["velocity"]["coverage_velocity_per_week"] is None
        assert out["forecast"]["weeks_to_full_coverage"] == 0.0

    def test_sparse_short_history_is_not_confident(self) -> None:
        out = _build(
            assumptions=[_assumption(i) for i in range(1, 6)],
            evidence=[
                _evidence(1, assumption_id=1, day=1),
                _evidence(2, assumption_id=2, day=2),
                _evidence(3, assumption_id=3, result="INCONCLUSIVE", day=3),
            ],
            now=_day(4),
        )
        assert out["forecast"]["confident"] is False
        assert any("under two weeks" in c for c in out["forecast"]["caveats"])
        assert out["forecast"]["weeks_to_full_coverage"] is not None


class TestCadenceAndForecast:
    def test_steady_scenario_projects_exact_horizon(self) -> None:
        assumptions = [_assumption(i) for i in range(1, 6)]
        out = _build(
            assumptions=assumptions,
            evidence=[
                _evidence(1, assumption_id=1, day=1),
                _evidence(2, assumption_id=2, day=8),
                _evidence(3, assumption_id=3, day=15),
                _evidence(4, assumption_id=4, result="INCONCLUSIVE", day=22),
                _evidence(5, assumption_id=5, day=36),
            ],
            now=_day(42),
        )
        counts = out["counts"]
        assert counts["assumptions_with_evidence"] == 5
        assert counts["evidence_coverage_pct"] == 1.0
        assert counts["de_risked_count"] == 4
        assert counts["inconclusive_count"] == 1

        velocity = out["velocity"]
        assert velocity["evidence_span_days"] == 35.0
        assert velocity["overall_events_per_week"] == 1.0
        assert velocity["events_last_28_days"] == 3
        assert velocity["recent_events_per_week"] == 0.75
        assert velocity["trend"] == TREND_DECELERATING
        assert velocity["coverage_velocity_per_week"] == 1.0
        assert velocity["de_risk_velocity_per_week"] == 0.8

        forecast = out["forecast"]
        assert forecast["target_de_risked_count"] == 5
        assert forecast["remaining_for_coverage"] == 0
        assert forecast["weeks_to_full_coverage"] == 0.0
        assert forecast["remaining_for_target"] == 1
        assert forecast["weeks_to_de_risked_target"] == 1.25
        assert forecast["projected_de_risked_at"] == _day(42) + timedelta(
            weeks=1.25
        )
        assert forecast["confident"] is True
        assert forecast["caveats"] == []
        assert any("de-risked" in i for i in out["insights"])
        assert any("challenged" in i or "slowing" in i for i in out["insights"])

    def test_accelerating_recent_cadence(self) -> None:
        assumptions = [_assumption(i) for i in range(1, 6)]
        out = _build(
            assumptions=assumptions,
            evidence=[
                _evidence(1, assumption_id=1, day=1),
                _evidence(2, assumption_id=2, result="INCONCLUSIVE", day=2),
                _evidence(3, assumption_id=3, day=54),
                _evidence(4, assumption_id=4, day=55),
                _evidence(5, assumption_id=5, day=56),
                _evidence(6, assumption_id=1, day=57),
            ],
            now=_day(60),
        )
        velocity = out["velocity"]
        assert velocity["trend"] == TREND_ACCELERATING
        assert velocity["events_last_28_days"] == 4
        assert velocity["recent_events_per_week"] == 1.0
        assert velocity["overall_events_per_week"] == round(6 / (56 / 7), 3)
        assert any("accelerating" in i for i in out["insights"])

    def test_custom_target_reduces_remaining_work(self) -> None:
        assumptions = [_assumption(i) for i in range(1, 6)]
        evidence = [
            _evidence(1, assumption_id=1, day=1),
            _evidence(2, assumption_id=2, day=8),
            _evidence(3, assumption_id=3, day=15),
            _evidence(4, assumption_id=4, result="INCONCLUSIVE", day=22),
            _evidence(5, assumption_id=5, day=36),
        ]
        full = _build(
            assumptions=assumptions,
            evidence=evidence,
            target_de_risked_pct=1.0,
            now=_day(42),
        )
        partial = _build(
            assumptions=assumptions,
            evidence=evidence,
            target_de_risked_pct=0.75,
            now=_day(42),
        )
        assert full["forecast"]["target_de_risked_count"] == 5
        assert full["forecast"]["remaining_for_target"] == 1
        assert partial["forecast"]["target_de_risked_count"] == 4
        assert partial["forecast"]["remaining_for_target"] == 0
        assert partial["forecast"]["weeks_to_de_risked_target"] == 0.0

    def test_all_de_risked_is_complete_and_confident(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(1, assumption_id=1, day=1),
                _evidence(2, assumption_id=2, day=8),
            ],
            now=_day(10),
        )
        assert out["counts"]["de_risked_count"] == 2
        assert out["forecast"]["remaining_for_target"] == 0
        assert out["forecast"]["weeks_to_de_risked_target"] == 0.0
        assert out["forecast"]["projected_de_risked_at"] == _day(10)
        assert out["forecast"]["confident"] is True
        assert any(
            "All visible assumptions are de-risked" in i
            for i in out["insights"]
        )

    def test_no_de_risking_yet_has_no_de_risk_horizon(self) -> None:
        out = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(1, assumption_id=1, result="INCONCLUSIVE", day=1),
                _evidence(2, assumption_id=2, result="INCONCLUSIVE", day=8),
                _evidence(3, assumption_id=1, result="INCONCLUSIVE", day=15),
            ],
            now=_day(20),
        )
        assert out["counts"]["de_risked_count"] == 0
        assert out["velocity"]["de_risk_velocity_per_week"] is None
        assert out["forecast"]["weeks_to_de_risked_target"] is None
        assert any("de-risked" in c for c in out["forecast"]["caveats"])


class TestSchemaRoundTrip:
    def test_payload_round_trips_through_schema(self) -> None:
        payload = _build(
            assumptions=[_assumption(1), _assumption(2)],
            evidence=[
                _evidence(1, assumption_id=1, day=1),
                _evidence(2, assumption_id=2, day=8),
            ],
            now=_day(10),
        )
        out = ValidationMomentumOut(**payload)
        dumped = out.model_dump()
        assert dumped["project_id"] == 10
        assert dumped["counts"]["de_risked_count"] == 2
        assert dumped["velocity"]["trend"] == TREND_DECELERATING
        assert dumped["forecast"]["confident"] is True
        assert dumped["meta"]["model"] == "validation_momentum_v1"

"""Tests for the project-level A/B experiment portfolio digest.

Covers the pure ``build_ab_test_summary`` aggregator and the
``GET /projects/{project_id}/experiments/summary`` route.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.simulation.ab_test_analysis import (
    VERDICT_INCONCLUSIVE,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_SIGNIFICANT,
    VERDICT_TRENDING,
)
from app.simulation.ab_test_summary import (
    NEXT_ACTION_MORE_DATA,
    NEXT_ACTION_NO_EXPERIMENTS,
    NEXT_ACTION_SIGNIFICANT_WINNERS,
    NEXT_ACTION_TRENDING,
    build_ab_test_summary,
)


class _FakeProject:
    def __init__(self, project_id: int = 10, user_id: int = 42) -> None:
        self.id = project_id
        self.user_id = user_id


class _FakeExperiment:
    def __init__(
        self,
        experiment_id: int,
        *,
        name: str = "Headline test",
        verdict: str = VERDICT_SIGNIFICANT,
        significant: bool = True,
        winner: str | None = "New",
        absolute_uplift: float | None = 0.06,
        relative_uplift_pct: float | None = 60.0,
        visitors_a: int = 1000,
        conversions_a: int = 100,
        visitors_b: int = 1000,
        conversions_b: int = 160,
    ) -> None:
        self.id = experiment_id
        self.project_id = 10
        self.name = name
        self.verdict = verdict
        self.significant = significant
        self.winner = winner
        self.absolute_uplift = absolute_uplift
        self.relative_uplift_pct = relative_uplift_pct
        self.visitors_a = visitors_a
        self.conversions_a = conversions_a
        self.visitors_b = visitors_b
        self.conversions_b = conversions_b
        self.created_at = datetime(2026, 8, 1, tzinfo=UTC)


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    _NO_PROJECT = object()

    def __init__(
        self,
        *,
        project: _FakeProject | object | None = None,
        experiments: list[_FakeExperiment] | None = None,
    ) -> None:
        self._no_project = project is self._NO_PROJECT
        self.project = (
            project
            if project is not None and project is not self._NO_PROJECT
            else _FakeProject()
        )
        self.experiments = experiments if experiments is not None else []

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            if self._no_project:
                return _FakeQuery([])
            return _FakeQuery([self.project])
        if name == "AbTestExperiment":
            return _FakeQuery(self.experiments)
        return _FakeQuery([])


def _call_summary(
    *,
    project_id: int = 10,
    session: _FakeSession | None = None,
):
    from app.api.v1.experiments import get_ab_test_experiments_summary

    return get_ab_test_experiments_summary(
        project_id=project_id,
        db=session if session is not None else _FakeSession(),
        current_user=type("U", (), {"id": 42})(),
    )


class TestAggregation:
    def test_empty_registry_returns_zeroed_digest(self) -> None:
        out = build_ab_test_summary([], 10)

        assert out["project_id"] == 10
        assert out["total_experiments"] == 0
        assert out["verdict_counts"] == {
            VERDICT_SIGNIFICANT: 0,
            VERDICT_TRENDING: 0,
            VERDICT_INCONCLUSIVE: 0,
            VERDICT_INSUFFICIENT_DATA: 0,
        }
        assert out["significant_win_rate"] is None
        assert out["total_visitors"] == 0
        assert out["total_conversions"] == 0
        assert out["overall_conversion_rate"] is None
        assert out["mean_absolute_uplift"] is None
        assert out["median_relative_uplift_pct"] is None
        assert out["next_action"] == NEXT_ACTION_NO_EXPERIMENTS
        assert out["top_winners"] == []
        assert out["trending_experiments"] == []

    def test_mixed_registry_counts_verdicts_and_uplifts(self) -> None:
        rows = [
            _FakeExperiment(1),
            _FakeExperiment(
                2,
                name="CTA copy",
                verdict=VERDICT_TRENDING,
                significant=False,
                absolute_uplift=0.02,
                relative_uplift_pct=20.0,
                visitors_a=500,
                conversions_a=50,
                visitors_b=500,
                conversions_b=60,
            ),
            _FakeExperiment(
                3,
                name="Pricing page",
                verdict=VERDICT_INCONCLUSIVE,
                significant=False,
                winner="Control",
                absolute_uplift=-0.005,
                relative_uplift_pct=-5.0,
                visitors_a=1000,
                conversions_a=100,
                visitors_b=1000,
                conversions_b=95,
            ),
            _FakeExperiment(
                4,
                name="Early traffic",
                verdict=VERDICT_INSUFFICIENT_DATA,
                significant=False,
                winner=None,
                absolute_uplift=0.1,
                relative_uplift_pct=100.0,
                visitors_a=10,
                conversions_a=1,
                visitors_b=10,
                conversions_b=2,
            ),
        ]

        out = build_ab_test_summary(rows, 10)

        assert out["total_experiments"] == 4
        assert out["verdict_counts"] == {
            VERDICT_SIGNIFICANT: 1,
            VERDICT_TRENDING: 1,
            VERDICT_INCONCLUSIVE: 1,
            VERDICT_INSUFFICIENT_DATA: 1,
        }
        assert out["significant_count"] == 1
        assert out["trending_count"] == 1
        assert out["inconclusive_count"] == 1
        assert out["insufficient_data_count"] == 1
        assert out["unclassified_count"] == 0
        assert out["significant_win_rate"] == pytest.approx(0.25)
        assert out["control_won_count"] == 1
        assert out["challenger_won_count"] == 3
        assert out["total_visitors"] == 5020
        assert out["total_conversions"] == 568
        assert out["overall_conversion_rate"] == pytest.approx(
            568 / 5020, abs=1e-6
        )
        assert out["mean_absolute_uplift"] == pytest.approx(0.04375)
        assert out["median_absolute_uplift"] == pytest.approx(0.04)
        assert out["median_relative_uplift_pct"] == pytest.approx(40.0)
        assert out["next_action"] == NEXT_ACTION_SIGNIFICANT_WINNERS
        assert [item["id"] for item in out["top_winners"]] == [1]
        assert [item["id"] for item in out["trending_experiments"]] == [2]

    def test_significant_winners_sorted_by_relative_uplift(self) -> None:
        rows = [
            _FakeExperiment(1, relative_uplift_pct=10.0),
            _FakeExperiment(2, name="Bigger win", relative_uplift_pct=90.0),
            _FakeExperiment(
                3,
                name="Missing uplift",
                relative_uplift_pct=None,
            ),
        ]

        out = build_ab_test_summary(rows, 10)

        assert [item["id"] for item in out["top_winners"]] == [2, 1, 3]
        assert out["median_relative_uplift_pct"] == pytest.approx(50.0)

    def test_trending_rows_sorted_by_absolute_uplift(self) -> None:
        rows = [
            _FakeExperiment(
                1,
                name="Small lead",
                verdict=VERDICT_TRENDING,
                significant=False,
                absolute_uplift=0.01,
            ),
            _FakeExperiment(
                2,
                name="Bigger lead",
                verdict=VERDICT_TRENDING,
                significant=False,
                absolute_uplift=0.05,
            ),
        ]

        out = build_ab_test_summary(rows, 10)

        assert [item["id"] for item in out["trending_experiments"]] == [2, 1]
        assert out["next_action"] == NEXT_ACTION_TRENDING

    def test_ties_and_missing_uplift_are_not_counted_as_wins(self) -> None:
        rows = [
            _FakeExperiment(1, absolute_uplift=0.0, winner=None),
            _FakeExperiment(2, absolute_uplift=None, winner=None),
        ]

        out = build_ab_test_summary(rows, 10)

        assert out["control_won_count"] == 0
        assert out["challenger_won_count"] == 0
        assert out["mean_absolute_uplift"] == 0.0
        assert out["median_absolute_uplift"] == 0.0

    def test_negative_uplift_counts_as_control_win(self) -> None:
        rows = [
            _FakeExperiment(
                1,
                name="Control wins",
                winner="Control",
                absolute_uplift=-0.03,
                relative_uplift_pct=-15.0,
            )
        ]

        out = build_ab_test_summary(rows, 10)

        assert out["control_won_count"] == 1
        assert out["challenger_won_count"] == 0
        assert out["median_absolute_uplift"] == pytest.approx(-0.03)

    def test_non_finite_uplifts_are_ignored(self) -> None:
        rows = [
            _FakeExperiment(1, absolute_uplift=0.04, relative_uplift_pct=40.0),
            _FakeExperiment(
                2,
                name="NaN row",
                absolute_uplift=float("nan"),
                relative_uplift_pct=float("inf"),
            ),
        ]

        out = build_ab_test_summary(rows, 10)

        assert out["mean_absolute_uplift"] == pytest.approx(0.04)
        assert out["median_absolute_uplift"] == pytest.approx(0.04)
        assert out["median_relative_uplift_pct"] == pytest.approx(40.0)

    def test_unknown_verdict_is_counted_separately(self) -> None:
        rows = [_FakeExperiment(1, verdict="EXOTIC", significant=False)]

        out = build_ab_test_summary(rows, 10)

        assert out["unclassified_count"] == 1
        assert out["significant_count"] == 0
        assert out["verdict_counts"][VERDICT_SIGNIFICANT] == 0
        assert out["next_action"] == NEXT_ACTION_MORE_DATA


class TestRoute:
    def test_route_returns_summary_payload(self) -> None:
        session = _FakeSession(experiments=[_FakeExperiment(1)])

        out = _call_summary(session=session)

        assert out.project_id == 10
        assert out.total_experiments == 1
        assert out.significant_count == 1
        assert out.significant_win_rate == pytest.approx(1.0)
        assert out.next_action == NEXT_ACTION_SIGNIFICANT_WINNERS
        assert [row.id for row in out.top_winners] == [1]
        assert out.trending_experiments == []

    def test_route_requires_owned_project(self) -> None:
        session = _FakeSession(project=_FakeSession._NO_PROJECT)

        with pytest.raises(HTTPException) as exc:
            _call_summary(session=session)

        assert exc.value.status_code == 404

    def test_summary_route_precedes_detail_route(self) -> None:
        """``summary`` must win over the ``{experiment_id}`` path param."""
        from app.api.v1.experiments import router

        paths = [route.path for route in router.routes]
        assert paths.index(
            "/projects/{project_id}/experiments/summary"
        ) < paths.index(
            "/projects/{project_id}/experiments/{experiment_id}"
        )

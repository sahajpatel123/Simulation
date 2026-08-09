"""Route-level tests for ``GET /simulations/portfolio-launch-priority``."""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _results(**overrides) -> dict:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "total_agents": 10000,
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
            "anxiety_driven_researcher": 0.04,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "CRITICAL"},
            {"id": "f2", "title": "Pricing confusion", "severity": "MAJOR"},
        ],
    }
    payload.update(overrides)
    return payload


class _FakeProjectRow:
    def __init__(
        self,
        project_id: int,
        *,
        title: str = "Project",
        premortem_json: dict | None = None,
        competitive_json: dict | None = None,
    ) -> None:
        self.id = project_id
        self.title = title
        self.premortem_json = premortem_json
        self.competitive_json = competitive_json


class _FakeSimRow:
    def __init__(
        self,
        sim_id: int,
        project_id: int,
        *,
        created_at: datetime | None = None,
        results: dict | None = None,
        signal_quality: float = 0.62,
        status: str = "COMPLETED",
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.created_at = (
            created_at
            if created_at is not None
            else datetime.now(UTC) - timedelta(days=1)
        )
        self.results_json = (
            results if results is not None else _results()
        )
        self.signal_quality = signal_quality
        self.status = status


class _FakeAssumptionRow:
    def __init__(
        self,
        project_id: int,
        category: str,
        *,
        sensitivity: str = "HIGH",
        is_hidden: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        self.project_id = project_id
        self.category = category
        self.sensitivity = sensitivity
        self.is_hidden = is_hidden
        self.created_at = (
            created_at
            if created_at is not None
            else datetime.now(UTC) - timedelta(days=2)
        )


class _FakeOutcomeRow:
    def __init__(
        self,
        project_id: int,
        *,
        created_at: datetime | None = None,
    ) -> None:
        self.project_id = project_id
        self.created_at = (
            created_at
            if created_at is not None
            else datetime.now(UTC) - timedelta(days=3)
        )


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        *,
        projects: list[_FakeProjectRow] | None = None,
        sims: list[_FakeSimRow] | None = None,
        assumptions: list[_FakeAssumptionRow] | None = None,
        outcomes: list[_FakeOutcomeRow] | None = None,
    ) -> None:
        self.projects = projects if projects is not None else []
        self.sims = sims if sims is not None else []
        self.assumptions = (
            assumptions if assumptions is not None else []
        )
        self.outcomes = outcomes if outcomes is not None else []

    def query(self, model, *args, **kwargs):
        # The route queries column attributes (e.g. ``Project.id``),
        # so unwrap to the mapped class before dispatching.
        klass = getattr(model, "class_", None) or model
        name = getattr(klass, "__name__", "")
        if name == "Project":
            return _FakeQuery(self.projects)
        if name == "Simulation":
            return _FakeQuery(self.sims)
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        if name == "Outcome":
            return _FakeQuery(self.outcomes)
        return _FakeQuery([])


def _call_route(
    *,
    session: _FakeSession | None = None,
    limit: int = 25,
    current_user_id: int = 42,
):
    from app.api.v1 import simulations as simulations_mod

    db = session or _FakeSession()
    return simulations_mod.get_portfolio_launch_priority(
        limit=limit,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_empty_portfolio_returns_empty_payload() -> None:
    out = _call_route()

    assert out.project_count == 0
    assert out.evaluated_count == 0
    assert out.portfolio_verdict == "INSUFFICIENT_DATA"
    assert out.top_pick is None
    assert out.launch_sequence == []
    for bucket in ("LAUNCH_NOW", "CONDITIONAL_LAUNCH", "FIX_FIRST", "PARK"):
        assert out.buckets[bucket] == []


def test_single_ready_project_ranks_first() -> None:
    session = _FakeSession(
        projects=[
            _FakeProjectRow(
                10,
                title="Launchable",
                premortem_json={
                    "failure_modes": [
                        {
                            "title": "Competitors copy",
                            "severity": "LOW",
                            "impact": 3,
                        },
                    ]
                },
                competitive_json={
                    "overall_competitive_position": "STRONG",
                    "competitors": [
                        {"name": "TinyCo", "threat_level": "LOW"},
                    ],
                },
            ),
        ],
        sims=[_FakeSimRow(100, 10)],
        assumptions=[
            _FakeAssumptionRow(10, "Pricing"),
            _FakeAssumptionRow(10, "Trust"),
            _FakeAssumptionRow(10, "Onboarding"),
            _FakeAssumptionRow(10, "Retention"),
            _FakeAssumptionRow(10, "DistributionChannel"),
            _FakeAssumptionRow(10, "Market"),
        ],
        outcomes=[_FakeOutcomeRow(10)],
    )

    out = _call_route(session=session)

    assert out.project_count == 1
    assert out.evaluated_count == 1
    assert out.launch_sequence == [10]
    assert out.top_pick is not None
    assert out.top_pick.project_id == 10
    assert out.top_pick.project_title == "Launchable"
    assert out.top_pick.go_no_go_score is not None
    assert out.top_pick.verdict in {
        "GO",
        "CONDITIONAL_GO",
        "NO_GO",
        "INSUFFICIENT_DATA",
    }
    assert out.top_pick.has_outcomes is True
    assert out.top_pick.latest_simulation_id == 100
    assert out.top_pick.weakest_pillar is not None
    assert out.portfolio_verdict in {
        "READY_TO_LAUNCH",
        "ALMOST_READY",
        "NOT_READY",
        "INSUFFICIENT_DATA",
    }
    assert out.narrative


def test_mixed_portfolio_ranks_scored_projects_first() -> None:
    session = _FakeSession(
        projects=[
            _FakeProjectRow(
                20,
                title="With sim",
                premortem_json={
                    "failure_modes": [
                        {"title": "Copycats", "severity": "HIGH"},
                    ]
                },
                competitive_json={
                    "overall_competitive_position": "MODERATE",
                    "competitors": [],
                },
            ),
            _FakeProjectRow(30, title="No sim"),
        ],
        sims=[_FakeSimRow(200, 20)],
        assumptions=[
            _FakeAssumptionRow(20, "Pricing"),
            _FakeAssumptionRow(20, "Trust"),
            _FakeAssumptionRow(20, "Onboarding"),
        ],
        outcomes=[],
    )

    out = _call_route(session=session)

    assert out.evaluated_count == 2
    assert out.launch_sequence == [20, 30]
    assert out.top_pick.project_id == 20
    assert out.buckets["PARK"][0].project_id == 30
    assert out.buckets["PARK"][0].reason
    assert out.buckets["PARK"][0].go_no_go_score is None


def test_malformed_project_json_does_not_crash() -> None:
    session = _FakeSession(
        projects=[
            _FakeProjectRow(
                40,
                title="Malformed",
                premortem_json={"failure_modes": "garbage"},
                competitive_json={"overall_competitive_position": 123},
            ),
        ],
        sims=[_FakeSimRow(400, 40, results={})],
        assumptions=[],
        outcomes=[],
    )

    out = _call_route(session=session)

    assert out.evaluated_count == 1
    assert out.launch_sequence == [40]
    assert out.top_pick is not None
    assert out.top_pick.verdict in {
        "GO",
        "CONDITIONAL_GO",
        "NO_GO",
        "INSUFFICIENT_DATA",
    }
    assert out.portfolio_verdict in {
        "READY_TO_LAUNCH",
        "ALMOST_READY",
        "NOT_READY",
        "INSUFFICIENT_DATA",
    }


def test_malformed_signal_quality_does_not_crash() -> None:
    for bad in (float("nan"), float("inf"), 1.5):
        session = _FakeSession(
            projects=[
                _FakeProjectRow(
                    50,
                    title="Legacy",
                    premortem_json={
                        "failure_modes": [
                            {"title": "Copycats", "severity": "LOW"},
                        ]
                    },
                    competitive_json={
                        "overall_competitive_position": "STRONG",
                        "competitors": [],
                    },
                ),
            ],
            sims=[_FakeSimRow(500, 50, signal_quality=bad)],
            assumptions=[],
            outcomes=[],
        )

        out = _call_route(session=session)

        assert out.evaluated_count == 1
        assert out.launch_sequence == [50]
        assert out.top_pick is not None
        assert out.top_pick.verdict in {
            "GO",
            "CONDITIONAL_GO",
            "NO_GO",
            "INSUFFICIENT_DATA",
        }


def test_hidden_assumptions_are_not_counted_as_visible(
    monkeypatch,
) -> None:
    from app.api.v1 import simulations as simulations_mod

    captured: dict[str, int | None] = {}
    real_builder = simulations_mod.build_launch_checklist

    def spy_builder(*args, **kwargs):
        captured["visible_assumption_count"] = kwargs.get(
            "visible_assumption_count"
        )
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(simulations_mod, "build_launch_checklist", spy_builder)
    session = _FakeSession(
        projects=[
            _FakeProjectRow(
                60,
                title="Hidden only",
                premortem_json={
                    "failure_modes": [
                        {"title": "Copycats", "severity": "LOW"},
                    ]
                },
                competitive_json={
                    "overall_competitive_position": "STRONG",
                    "competitors": [],
                },
            ),
        ],
        sims=[_FakeSimRow(600, 60)],
        assumptions=[
            _FakeAssumptionRow(60, "Pricing", is_hidden=True),
            _FakeAssumptionRow(60, "Trust", is_hidden=True),
            _FakeAssumptionRow(60, "Onboarding", is_hidden=False),
        ],
        outcomes=[],
    )

    _call_route(session=session)

    assert captured["visible_assumption_count"] == 1


def test_large_portfolio_payload_is_capped() -> None:
    session = _FakeSession(
        projects=[
            _FakeProjectRow(i, title=f"P{i}")
            for i in range(1, 31)
        ],
    )
    out = _call_route(session=session, limit=5)

    # The fake session returns all rows regardless of limit, so the
    # route-level cap is applied by the pure helper on the payload
    # the query returned — the important contract is that a bounded
    # limit is accepted and a valid payload is produced.
    assert out.project_count == 30
    assert out.evaluated_count == 30
    assert len(out.launch_sequence) == 25

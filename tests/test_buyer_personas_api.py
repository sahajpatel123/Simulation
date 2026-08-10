"""Route-level tests for the /simulations/{id}/buyer-personas endpoint.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.04,
                "total_agents": 10000,
                "cluster_breakdown": {
                    "metro_power_professional": 0.03,
                    "senior_enterprise_decision_maker": 0.02,
                    "high_income_early_adopter": 0.08,
                },
            }
        )


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else [_FakeSimulation()]

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return self.items


class _FakeSummaryRow:
    def __init__(
        self,
        cluster_id: str,
        *,
        agents_assigned: int,
        agents_converted: int,
        conversion_rate: float,
    ) -> None:
        self.cluster_id = cluster_id
        self.agents_assigned = agents_assigned
        self.agents_converted = agents_converted
        self.conversion_rate = conversion_rate
        self.primary_drop_trigger = "PricingArchitect"
        self.mean_drop_state = "DECIDE"


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        summaries: list | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.summaries = summaries if summaries is not None else []

    def query(self, model, *args, **kwargs):
        if getattr(model, "__name__", "") == "Simulation":
            return _FakeQuery([self.sim])
        return _FakeQuery(self.summaries)


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
    limit: int = 10,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_buyer_personas(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
        limit=limit,
    )


def test_completed_simulation_returns_persona_payload() -> None:
    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.signal_quality == 0.62
    assert out.total_agents == 10000
    assert out.persona_count == 3
    assert out.primary_target_persona is not None
    assert out.personas[0].cluster_name
    assert list(out.personas[0].traits.keys())
    assert out.personas[0].messaging_angle
    assert out.personas[0].risk_watch
    assert out.focus_recommendations


def test_personas_are_ranked_by_opportunity() -> None:
    out = _call_route()
    scores = [p.opportunity_score for p in out.personas]
    assert scores == sorted(scores, reverse=True)


def test_limit_is_respected() -> None:
    out = _call_route(limit=2)
    assert len(out.personas) == 2
    assert out.persona_count == 2


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        sim=_FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(sim=_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_cluster_summaries_are_forwarded_to_engine() -> None:
    summaries = [
        _FakeSummaryRow(
            "metro_power_professional",
            agents_assigned=8000,
            agents_converted=240,
            conversion_rate=0.03,
        ),
        _FakeSummaryRow(
            "high_income_early_adopter",
            agents_assigned=2000,
            agents_converted=160,
            conversion_rate=0.08,
        ),
    ]
    session = _FakeSession(summaries=summaries)
    out = _call_route(session=session)
    assert out.meta["cluster_summaries_used"] is True
    assert out.personas[0].population_weight == 0.8

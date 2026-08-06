"""Route-level tests for ``GET /api/v1/simulations/{id}/quality``."""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

from app.simulation.clusters.registry import ClusterRegistry


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _healthy_results() -> dict:
    clusters = ClusterRegistry().all_clusters()
    rates = {
        c.cluster_id: round(0.03 + index * 0.0008, 6)
        for index, c in enumerate(clusters)
    }
    pwc = round(
        sum(c.population_weight * rates[c.cluster_id] for c in clusters),
        6,
    )
    converted = int(round(pwc * 10_000))
    return {
        "mean_conversion_rate": pwc,
        "population_weighted_conversion": pwc,
        "total_agents": 10_000,
        "converted": converted,
        "cluster_breakdown": rates,
        "domain_findings": [{"domain": "PricingArchitect", "severity": "WARNING"}],
        "raw_funnel": {
            "total_agents": 10_000,
            "converted": converted,
            "conversion_rate": pwc,
            "stage_counts": {
                "ARRIVE": 10_000,
                "BROWSE": 7_000,
                "CONSIDER": 4_000,
                "DECIDE": 2_000,
                "PURCHASE": converted,
            },
            "stage_metrics": [
                {
                    "state": "ARRIVE",
                    "agent_count": 10_000,
                    "entry_rate": 1.0,
                    "drop_off_rate": 0.3,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "BROWSE",
                    "agent_count": 7_000,
                    "entry_rate": 0.7,
                    "drop_off_rate": 0.43,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "CONSIDER",
                    "agent_count": 4_000,
                    "entry_rate": 0.4,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
                {
                    "state": "DECIDE",
                    "agent_count": 2_000,
                    "entry_rate": 0.2,
                    "drop_off_rate": 0.5,
                    "avg_time_seconds": 1.0,
                },
            ],
        },
    }


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
        signal_quality: float | None = 0.62,
        environment_id: int | None = 7,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.signal_quality = signal_quality
        self.environment_id = environment_id
        self.results_json = (
            results if results is not None else _healthy_results()
        )


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self.sim = sim or _FakeSimulation()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim])
        return _FakeQuery()


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_simulation_quality(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_completed_simulation_returns_quality_payload() -> None:
    out = _call_route()
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.status == "COMPLETED"
    assert out.signal_quality == 0.62
    assert out.trust_score == 1.0
    assert out.verdict == "PASS"
    assert out.summary.total_checks == 11
    assert out.summary.passed_checks == 11
    assert out.recommendations == []


def test_quality_payload_serialises_via_schema() -> None:
    from app.schemas.simulation_quality import SimulationQualityOut

    out = _call_route()
    payload = SimulationQualityOut.model_validate(out)
    assert payload.verdict == "PASS"
    assert len(payload.checks) == 11


def test_broken_results_return_review_with_recommendations() -> None:
    results = _healthy_results()
    results.pop("raw_funnel", None)
    clusters = ClusterRegistry().all_clusters()
    results["cluster_breakdown"] = {
        c.cluster_id: 0.04 for c in clusters[:40]
    }
    results["converted"] = 20_000
    session = _FakeSession(sim=_FakeSimulation(results=results))
    out = _call_route(session=session)
    assert out.verdict == "REVIEW"
    assert out.summary.failed_checks >= 1
    assert out.recommendations


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

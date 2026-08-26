"""
Route-level tests for ``GET /api/v1/simulations/{id}/funnel-elasticity``.

Covers ownership lookup, status gates, missing-data handling, and the
returned response model — mirroring the journey-analytics API contract.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

# ``app.api.v1`` eagerly imports the billing router, which imports the
# razorpay SDK. In test environments without the package installed (or
# with a broken transitive dependency), stub it the same way the existing
# route-level tests do so we can import the simulations module.
if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


from app.schemas.funnel_elasticity import FunnelElasticityOut  # noqa: E402


def _results() -> dict:
    return {
        "cluster_weights": {"c0": 0.6, "c1": 0.4},
        "per_cluster_matrices": {
            "c0": {
                "ARRIVE->BROWSE": 0.95,
                "BROWSE->CONSIDER": 0.80,
                "CONSIDER->DECIDE": 0.70,
                "DECIDE->PURCHASE": 0.50,
            },
            "c1": {},
        },
    }


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        project_id: int = 10,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.status = status
        self.error_message = error_message
        self.results_json = results if results is not None else _results()


class _FakeQuery:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self.rows = self.rows[:n]
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self.sim = sim or _FakeSimulation()

    def query(self, *args, **kwargs):
        return _FakeQuery([self.sim])


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
) -> FunnelElasticityOut:
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_simulation_funnel_elasticity(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_completed_simulation_returns_elasticity_payload() -> None:
    out = _call_route()

    assert isinstance(out, FunnelElasticityOut)
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert 0.0 <= out.naive_conversion <= 1.0
    assert out.loop_adjusted_conversion >= out.naive_conversion - 1e-9
    assert len(out.edges) == 4
    assert len(out.ranking) == 4
    assert out.recommendation.startswith("Across")
    assert out.meta["weighted"] is True
    top_edge = out.ranking[0]
    assert any(
        f"{e.from_state}->{e.to_state}" == top_edge for e in out.edges
    )
    assert sum(c.weighted_vote_share for c in out.cluster_consensus) == pytest.approx(1.0, abs=1e-6)


def test_route_honours_simulation_id() -> None:
    out = _call_route(
        simulation_id=77,
        session=_FakeSession(_FakeSimulation(sim_id=77)),
    )
    assert out.simulation_id == 77


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        _FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_running_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="RUNNING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409
    assert "RUNNING" in exc.value.detail


def test_empty_results_raises_422() -> None:
    session = _FakeSession(
        _FakeSimulation(status="COMPLETED", results={})
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_missing_matrix_data_raises_404() -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "cluster_breakdown": {"c0": 0.04},
                "raw_funnel": {"conversion_rate": 0.04},
            }
        )
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 404
    assert "Re-run the simulation" in exc.value.detail


def test_missing_owned_simulation_raises_404() -> None:
    session = _FakeSession(_FakeSimulation(sim_id=999))
    # Simulate the ownership query returning no row.
    session.sim = None
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_id=999, session=session)
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail


def test_malformed_weights_still_yield_valid_response_model() -> None:
    results = _results()
    results["cluster_weights"] = {
        "c0": float("inf"),
        "c1": float("nan"),
    }
    session = _FakeSession(_FakeSimulation(results=results))

    out = _call_route(session=session)

    assert isinstance(out, FunnelElasticityOut)
    assert all(0.0 <= e.lift_per_gain_pp for e in out.edges)
    assert all(c.population_weight > 0.0 for c in out.per_cluster_top_edges)
    assert out.meta["weighted"] is False

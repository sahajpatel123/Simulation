"""
Route-level tests for ``GET /api/v1/simulations/{id}/journey/trend``.

Covers ownership lookup, status gates, portfolio filtering (simulations
without persisted journey data are skipped), the anchor flag, and the
returned response model.
"""
from __future__ import annotations

import sys
import types

import pytest
from fastapi import HTTPException

# ``app.api.v1`` eagerly imports the billing router, which imports the
# razorpay SDK. Stub it the same way the existing route-level tests do so we
# can import the simulations module in environments without the package.
if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.journey_trend import JourneyTrendOut  # noqa: E402


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


def _strong_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.95
    return results


def _weak_results() -> dict:
    results = _results()
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.10
    return results


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


class _FakeTrendRow:
    def __init__(
        self,
        sim_id: int,
        project_id: int,
        results: dict | None,
        created_at: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = project_id
        self.created_at = created_at
        self.results_json = results


class _FakeQuery:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        return self

    def first(self):
        return self.session.sim

    def all(self):
        return self.session.rows


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        rows: list[_FakeTrendRow] | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.rows = rows if rows is not None else []

    def query(self, *args, **kwargs):
        return _FakeQuery(self)


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    session: _FakeSession | None = None,
) -> JourneyTrendOut:
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_simulation_journey_trend(
        simulation_id=simulation_id,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def _trend_rows() -> list[_FakeTrendRow]:
    return [
        _FakeTrendRow(1, 10, _weak_results(), "2026-01-01T00:00:00Z"),
        _FakeTrendRow(2, 10, _results(), "2026-02-01T00:00:00Z"),
        _FakeTrendRow(3, 11, _strong_results(), "2026-03-01T00:00:00Z"),
    ]


def test_trend_returns_portfolio_series_with_anchor() -> None:
    out = _call_route(
        simulation_id=2,
        session=_FakeSession(
            _FakeSimulation(sim_id=2),
            rows=_trend_rows(),
        ),
    )

    assert isinstance(out, JourneyTrendOut)
    assert out.simulation_id == 2
    assert out.project_id == 10
    assert [p.simulation_id for p in out.points] == [1, 2, 3]
    assert [p.is_anchor for p in out.points] == [False, True, False]
    assert out.summary.included_count == 3
    assert out.summary.raw_count == 3
    assert out.summary.skipped_count == 0
    assert out.summary.best_point is not None
    assert out.summary.best_point.simulation_id == 3
    assert out.summary.worst_point is not None
    assert out.summary.worst_point.simulation_id == 1
    assert out.summary.trend_slope > 0.0
    assert out.anchor_percentile_rank == 50.0
    assert out.insights
    assert out.generated_at


def test_trend_skips_simulations_without_journey_data() -> None:
    rows = _trend_rows() + [
        _FakeTrendRow(
            4,
            12,
            {"cluster_breakdown": {"c0": 0.04}, "conversion_rate": 0.04},
            "2026-04-01T00:00:00Z",
        )
    ]
    out = _call_route(simulation_id=3, session=_FakeSession(rows=rows))

    assert out.summary.raw_count == 4
    assert out.summary.included_count == 3
    assert out.summary.skipped_count == 1
    assert [p.simulation_id for p in out.points] == [1, 2, 3]


def test_trend_empty_portfolio_still_returns_anchor_point() -> None:
    out = _call_route(
        session=_FakeSession(rows=[_FakeTrendRow(1, 10, _results())])
    )

    assert isinstance(out, JourneyTrendOut)
    assert out.summary.included_count == 1
    assert out.points[0].simulation_id == 1
    assert out.points[0].is_anchor is True
    assert out.anchor_percentile_rank is None
    assert out.insights


def test_trend_honours_simulation_id() -> None:
    out = _call_route(
        simulation_id=77,
        session=_FakeSession(
            _FakeSimulation(sim_id=77),
            rows=_trend_rows(),
        ),
    )
    assert out.simulation_id == 77


def test_trend_running_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="RUNNING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409
    assert "RUNNING" in exc.value.detail


def test_trend_failed_simulation_raises_422() -> None:
    session = _FakeSession(
        _FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_trend_missing_journey_data_raises_404() -> None:
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


def test_trend_missing_owned_simulation_raises_404() -> None:
    session = _FakeSession()
    session.sim = None
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_id=999, session=session)
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail

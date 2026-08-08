"""
Route-level tests for ``GET /api/v1/simulations/{id}/journey/category-benchmark``.

Covers ownership lookup, status gates, category derivation, cohort filtering
(simulations without persisted journey data are skipped), the sample limit,
and the returned response model.
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

from app.schemas.journey_benchmark import (  # noqa: E402
    JourneyCategoryBenchmarkOut,
)


def _results(product_type: str = "saas") -> dict:
    return {
        "product_type_detected": product_type,
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


def _strong_results(product_type: str = "saas") -> dict:
    results = _results(product_type)
    results["per_cluster_matrices"]["c0"]["DECIDE->PURCHASE"] = 0.95
    return results


def _weak_results(product_type: str = "saas") -> dict:
    results = _results(product_type)
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


class _FakeCohortRow:
    def __init__(
        self,
        sim_id: int,
        results: dict | None,
    ) -> None:
        self.id = sim_id
        self.results_json = results


class _FakeQuery:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.limit_value: int | None = None

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n: int):
        self.limit_value = n
        return self

    def first(self):
        return self.session.sim

    def all(self):
        return self.session.cohort_rows


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        cohort_rows: list[_FakeCohortRow] | None = None,
    ) -> None:
        self.sim = sim or _FakeSimulation()
        self.cohort_rows = cohort_rows if cohort_rows is not None else []
        self.last_query: _FakeQuery | None = None

    def query(self, *args, **kwargs):
        self.last_query = _FakeQuery(self)
        return self.last_query


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the route test isolated from any local Redis instance."""
    from app.api.v1 import simulations as sim_mod

    monkeypatch.setattr(sim_mod, "cache_get_json", lambda *a, **k: None)
    monkeypatch.setattr(sim_mod, "cache_set_json", lambda *a, **k: None)


def _call_route(
    *,
    simulation_id: int = 1,
    current_user_id: int = 42,
    limit: int = 200,
    session: _FakeSession | None = None,
) -> JourneyCategoryBenchmarkOut:
    from app.api.v1 import simulations as sim_mod

    db = session or _FakeSession()
    return sim_mod.get_simulation_journey_category_benchmark(
        simulation_id=simulation_id,
        limit=limit,
        db=db,
        current_user=type("U", (), {"id": current_user_id})(),
    )


def _cohort_rows() -> list[_FakeCohortRow]:
    return [
        _FakeCohortRow(2, _strong_results()),
        _FakeCohortRow(3, _weak_results()),
    ]


def test_category_benchmark_returns_cohort_comparison() -> None:
    out = _call_route(session=_FakeSession(cohort_rows=_cohort_rows()))

    assert isinstance(out, JourneyCategoryBenchmarkOut)
    assert out.simulation_id == 1
    assert out.project_id == 10
    assert out.category == "saas"
    assert out.cohort_size == 2
    assert out.percentile_rank == pytest.approx(50.0)
    assert out.current.purchase_probability == pytest.approx(0.060933, abs=1e-5)
    assert out.distribution.most_common_primary_exit_stage == "BROWSE"
    assert out.meta["raw_completed_count"] == 2
    assert out.meta["skipped_without_journey_data"] == 0
    assert any("saas" in i for i in out.insights)


def test_category_benchmark_uses_current_simulation_category() -> None:
    session = _FakeSession(
        _FakeSimulation(results=_results("consumer_hardware")),
        cohort_rows=[
            _FakeCohortRow(2, _strong_results("consumer_hardware")),
            _FakeCohortRow(3, _weak_results("consumer_hardware")),
        ],
    )
    out = _call_route(session=session)

    assert out.category == "consumer_hardware"
    assert out.cohort_size == 2
    assert any("consumer hardware" in i for i in out.insights)


def test_category_benchmark_defaults_to_saas_without_detected_type() -> None:
    results = _results()
    results.pop("product_type_detected", None)
    out = _call_route(
        session=_FakeSession(
            _FakeSimulation(results=results),
            cohort_rows=_cohort_rows(),
        )
    )

    assert out.category == "saas"
    assert out.cohort_size == 2


def test_category_benchmark_skips_simulations_without_journey_data() -> None:
    rows = _cohort_rows() + [
        _FakeCohortRow(
            4,
            {"product_type_detected": "saas", "conversion_rate": 0.04},
        )
    ]
    out = _call_route(session=_FakeSession(cohort_rows=rows))

    assert out.cohort_size == 2
    assert out.meta["raw_completed_count"] == 3
    assert out.meta["skipped_without_journey_data"] == 1


def test_category_benchmark_empty_cohort_returns_empty_benchmark() -> None:
    out = _call_route(session=_FakeSession(cohort_rows=[]))

    assert out.cohort_size == 0
    assert out.percentile_rank is None
    assert out.distribution.median_purchase_probability is None
    assert out.insights
    assert "No journey-capable saas simulations on TheCee yet" in out.insights[0]


def test_category_benchmark_passes_sample_limit_to_query() -> None:
    session = _FakeSession(cohort_rows=_cohort_rows())
    out = _call_route(limit=50, session=session)

    assert out.cohort_size == 2
    assert session.last_query is not None
    assert session.last_query.limit_value == 50
    assert out.meta["sample_limit"] == 50


def test_category_benchmark_honours_simulation_id() -> None:
    out = _call_route(
        simulation_id=77,
        session=_FakeSession(
            _FakeSimulation(sim_id=77),
            cohort_rows=_cohort_rows(),
        ),
    )
    assert out.simulation_id == 77


def test_category_benchmark_running_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="RUNNING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409
    assert "RUNNING" in exc.value.detail


def test_category_benchmark_missing_journey_data_raises_404() -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "product_type_detected": "saas",
                "cluster_breakdown": {"c0": 0.04},
                "raw_funnel": {"conversion_rate": 0.04},
            }
        )
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 404
    assert "Re-run the simulation" in exc.value.detail


def test_category_benchmark_missing_owned_simulation_raises_404() -> None:
    session = _FakeSession()
    session.sim = None
    with pytest.raises(HTTPException) as exc:
        _call_route(simulation_id=999, session=session)
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail

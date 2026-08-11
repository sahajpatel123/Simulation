"""Route-level tests for ``GET /simulations/{id}/validation-experiment-plan/export``."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeSimulation:
    def __init__(
        self,
        *,
        status: str = "COMPLETED",
        results: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        self.id = 1
        self.project_id = 10
        self.environment_id = 5
        self.status = status
        self.results_json = results if results is not None else {"mean_conversion_rate": 0.04}
        self.signal_quality = 0.62
        self.error_message = error_message


class _FakeEnvironment:
    def __init__(self) -> None:
        self.id = 5
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0


class _FakeAssumption:
    def __init__(self, text: str, category: str = "PricingArchitect") -> None:
        self.text = text
        self.category = category
        self.sensitivity = "HIGH"
        self.impact_score = 7.0
        self.claim_confidence = None
        self.is_hidden = False


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | None = None,
        assumptions: list[_FakeAssumption] | None = None,
    ) -> None:
        self.sim = sim
        self.assumptions = assumptions if assumptions is not None else []

    def query(self, model: Any, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Environment":
            return _FakeQuery([_FakeEnvironment()])
        if name == "Assumption":
            return _FakeQuery(self.assumptions)
        return _FakeQuery([])


def _call_route(
    session: _FakeSession | None = None,
    *,
    format: str = "csv",
):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.export_validation_experiment_plan(
        simulation_id=1,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _stream_bytes(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_stream_bytes(response))


def test_route_returns_csv_export() -> None:
    response = _call_route(
        _FakeSession(
            _FakeSimulation(),
            assumptions=[
                _FakeAssumption("price exceeds willingness to pay"),
                _FakeAssumption("market demand is proven", "MarketSizeArchitect"),
            ],
        )
    )

    assert response.headers["content-type"].startswith("text/csv")
    assert "validation-experiment-plan-1.csv" in response.headers["Content-Disposition"]
    body = _body(response).decode("utf-8")
    assert "user_id,42" in body
    assert "section,Validation Sprint Summary" in body
    assert "section,Experiments" in body
    assert "price exceeds willingness to pay" in body
    assert "WILLINGNESS_TO_PAY_SURVEY" in body


def test_route_returns_json_export() -> None:
    response = _call_route(
        _FakeSession(
            _FakeSimulation(),
            assumptions=[_FakeAssumption("price exceeds willingness to pay")],
        ),
        format="json",
    )

    assert response.headers["content-type"].startswith("application/json")
    assert "validation-experiment-plan-1.json" in response.headers["Content-Disposition"]
    body = json.loads(_body(response).decode("utf-8"))
    assert body["metadata"]["simulation_id"] == 1
    plan = body["validation_experiment_plan"]
    assert plan["project_id"] == 10
    assert plan["summary"]["experiment_count"] >= 1
    assert plan["experiments"][0]["assumption_text"] == "price exceeds willingness to pay"


def test_route_accepts_uppercase_format() -> None:
    response = _call_route(
        _FakeSession(
            _FakeSimulation(),
            assumptions=[_FakeAssumption("price exceeds willingness to pay")],
        ),
        format="JSON",
    )

    body = json.loads(_body(response).decode("utf-8"))
    assert body["validation_experiment_plan"]["simulation_id"] == 1


def test_route_rejects_unsupported_format() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(_FakeSession(_FakeSimulation()), format="xml")
    assert exc.value.status_code == 400
    assert "xml" in exc.value.detail


def test_route_rejects_non_completed_simulation() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(_FakeSession(_FakeSimulation(status="PENDING")))
    assert exc.value.status_code == 409


def test_route_rejects_failed_simulation() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(
            _FakeSession(_FakeSimulation(status="FAILED", error_message="boom"))
        )
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_route_rejects_empty_results() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(_FakeSession(_FakeSimulation(results={})))
    assert exc.value.status_code == 422


def test_route_returns_404_when_simulation_missing() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(_FakeSession(sim=None))
    assert exc.value.status_code == 404


def test_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    paths = {r.path for r in sim_mod.router.routes}
    assert "/simulations/{simulation_id}/validation-experiment-plan/export" in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path[
        "/simulations/{simulation_id}/validation-experiment-plan/export"
    ]

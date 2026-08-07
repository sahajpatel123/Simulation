"""Route-level tests for the /simulations/{id}/findings/export endpoint."""
from __future__ import annotations

import asyncio
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
        self.environment_id = 5
        self.status = status
        self.error_message = error_message
        self.signal_quality = 0.62
        self.created_at = "2026-08-07T20:00:00+00:00"
        self.results_json = (
            results
            if results is not None
            else {
                "population_weighted_conversion": 0.04,
                "product_type_detected": "saas",
                "domain_findings": [
                    {
                        "severity": "CRITICAL",
                        "architect_name": "PricingArchitect",
                        "cluster_id": "metro_power_professional",
                        "finding": "price ceiling too low",
                        "conversion_impact": 0.042,
                    }
                ],
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
        return list(self.items)


class _FakeSession:
    def __init__(self, sim: object | None = None) -> None:
        self.sim = sim

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        return _FakeQuery([])


def _call_route(
    *,
    simulation_id: int = 1,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.get_findings_export(
        simulation_id=simulation_id,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_completed_simulation_returns_findings_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="findings-1.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "simulation_id,project_id,severity,architect_name,cluster_id" in body
    assert "1,10,CRITICAL,PricingArchitect,metro_power_professional" in body


def test_format_json_returns_findings_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"simulation_id": 1' in body
    assert '"PricingArchitect"' in body


def test_failed_simulation_raises_422() -> None:
    session = _FakeSession(_FakeSimulation(status="FAILED", error_message="boom"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_pending_simulation_raises_409() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_empty_results_raises_422() -> None:
    session = _FakeSession(_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422

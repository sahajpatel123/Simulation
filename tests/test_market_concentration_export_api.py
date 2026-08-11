"""Route-level tests for ``GET /simulations/{id}/market-concentration/export``."""

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
                "cluster_breakdown": {
                    "c1": 0.04,
                    "c2": 0.04,
                    "c3": 0.04,
                    "c4": 0.04,
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


_MISSING = object()


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


class _FakeSession:
    def __init__(
        self,
        sim: _FakeSimulation | object = _MISSING,
        summaries: list | None = None,
    ) -> None:
        self.sim = _FakeSimulation() if sim is _MISSING else sim
        self.summaries = summaries if summaries is not None else []

    def query(self, model: Any, *args, **kwargs):
        if getattr(model, "__name__", "") == "Simulation":
            return _FakeQuery([self.sim])
        return _FakeQuery(self.summaries)


def _call_route(
    session: _FakeSession | None = None,
    *,
    format: str = "csv",
    simulation_id: int = 1,
):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession()
    return sim_mod.export_market_concentration(
        simulation_id=simulation_id,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _stream_bytes(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _body(response: Any) -> bytes:
    return asyncio.run(_stream_bytes(response))


def test_route_returns_csv_export() -> None:
    response = _call_route()

    assert response.headers["content-type"].startswith("text/csv")
    assert "market-concentration-1.csv" in response.headers["Content-Disposition"]
    body = _body(response).decode("utf-8")
    assert "user_id,42" in body
    assert "section,Demand Concentration Summary" in body
    assert "section,Segment Demand Shares" in body
    assert "1,c1,c1,0.25,0.04,0.25," in body
    assert "section,Recommendations" in body
    assert "section,Meta" in body


def test_route_csv_body_is_utf8_bom_prefixed() -> None:
    response = _call_route()

    body = _body(response)
    assert body.startswith(b"\xef\xbb\xbf")
    assert int(response.headers["Content-Length"]) == len(body)


def test_route_returns_json_export() -> None:
    response = _call_route(format="json")

    assert response.headers["content-type"].startswith("application/json")
    assert "market-concentration-1.json" in response.headers["Content-Disposition"]
    body = json.loads(_body(response).decode("utf-8"))
    assert body["metadata"]["simulation_id"] == 1
    assert body["metadata"]["project_id"] == 10
    concentration = body["market_concentration"]
    assert concentration["simulation_id"] == 1
    assert concentration["project_id"] == 10
    assert concentration["verdict"] == "DIVERSIFIED"
    assert len(concentration["segment_shares"]) == 4


def test_route_accepts_uppercase_format() -> None:
    response = _call_route(format="JSON")

    body = json.loads(_body(response).decode("utf-8"))
    assert body["market_concentration"]["simulation_id"] == 1


def test_route_rejects_unsupported_format() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(format="xml")
    assert exc.value.status_code == 400
    assert "xml" in exc.value.detail


def test_route_rejects_failed_simulation() -> None:
    session = _FakeSession(
        sim=_FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_route_rejects_pending_simulation() -> None:
    session = _FakeSession(sim=_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 409


def test_route_rejects_empty_results() -> None:
    session = _FakeSession(sim=_FakeSimulation(results={}))
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 422


def test_route_returns_404_when_simulation_missing() -> None:
    session = _FakeSession(sim=None)
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 404


def test_route_forwards_cluster_summaries() -> None:
    summaries = [
        _FakeSummaryRow(
            "c1",
            agents_assigned=2500,
            agents_converted=100,
            conversion_rate=0.04,
        )
    ]
    session = _FakeSession(summaries=summaries)

    response = _call_route(session=session)
    body = _body(response).decode("utf-8")
    assert "cluster_summaries_used,True" in body


def test_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    path = "/simulations/{simulation_id}/market-concentration/export"
    paths = {r.path for r in sim_mod.router.routes}
    assert path in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path[path]

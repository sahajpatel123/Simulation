"""Route-level tests for ``GET /simulations/{id}/cluster-run-summaries/export``."""

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


_MISSING = object()


class _FakeSimulation:
    def __init__(
        self,
        sim_id: int = 1,
        *,
        status: str = "COMPLETED",
        error_message: str | None = None,
    ) -> None:
        self.id = sim_id
        self.project_id = 10
        self.status = status
        self.error_message = error_message
        self.created_at = "2026-08-12T09:00:00+00:00"


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


class _FakeSummaryRow:
    def __init__(
        self,
        cluster_id: str,
        *,
        row_id: int = 1,
        agents_assigned: int = 1000,
        agents_converted: int = 40,
        conversion_rate: float = 0.04,
    ) -> None:
        self.id = row_id
        self.cluster_id = cluster_id
        self.agents_assigned = agents_assigned
        self.agents_converted = agents_converted
        self.conversion_rate = conversion_rate
        self.drop_state_distribution = {"ARRIVE": 1000, "BROWSE": 600}
        self.mean_drop_state = "CONSIDER"
        self.architect_scores = {"PricingArchitect": 0.62}
        self.primary_drop_trigger = "price_sensitivity"
        self.signal_quality = 0.62
        self.claim_confidence_distribution = {"HIGH": 0.8}
        self.product_type = "saas"
        self.created_at = "2026-08-12T09:00:00+00:00"


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
    return sim_mod.export_cluster_run_summaries(
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
    session = _FakeSession(
        summaries=[
            _FakeSummaryRow("metro_power_professional"),
            _FakeSummaryRow("tier3_first_time_app_user", row_id=2),
        ]
    )
    response = _call_route(session=session)

    assert response.headers["content-type"].startswith("text/csv")
    assert "cluster-run-summaries-1.csv" in response.headers["Content-Disposition"]
    body = _body(response).decode("utf-8")
    assert "user_id,42" in body
    assert "simulation_id,1" in body
    assert "project_id,10" in body
    assert "section,Cluster Run Summary" in body
    assert "total_clusters,2" in body
    assert "total_agents_assigned,2000" in body
    assert "section,Cluster Run Rows" in body
    assert "metro_power_professional" in body
    assert "tier3_first_time_app_user" in body
    # CSV quoting doubles embedded quotes in JSON cells.
    assert '""PricingArchitect"":0.62' in body


def test_route_csv_body_is_utf8_bom_prefixed() -> None:
    response = _call_route()

    body = _body(response)
    assert body.startswith(b"\xef\xbb\xbf")
    assert int(response.headers["Content-Length"]) == len(body)


def test_route_export_responses_are_not_cached() -> None:
    for fmt in ("csv", "json"):
        response = _call_route(format=fmt)
        assert response.headers["Cache-Control"] == "no-store"
        assert int(response.headers["Content-Length"]) == len(_body(response))


def test_route_returns_json_export() -> None:
    session = _FakeSession(summaries=[_FakeSummaryRow("metro_power_professional")])
    response = _call_route(session=session, format="json")

    assert response.headers["content-type"].startswith("application/json")
    assert "cluster-run-summaries-1.json" in response.headers["Content-Disposition"]
    body = json.loads(_body(response).decode("utf-8"))
    assert body["metadata"]["simulation_id"] == 1
    assert body["metadata"]["project_id"] == 10
    payload = body["cluster_run_summaries"]
    assert payload["simulation_id"] == 1
    assert payload["project_id"] == 10
    assert payload["status"] == "COMPLETED"
    assert payload["total_clusters"] == 1
    assert payload["rows"][0]["cluster_id"] == "metro_power_professional"
    assert payload["rows"][0]["architect_scores"] == {"PricingArchitect": 0.62}


def test_route_accepts_uppercase_format() -> None:
    response = _call_route(format="JSON")

    body = json.loads(_body(response).decode("utf-8"))
    assert body["cluster_run_summaries"]["simulation_id"] == 1


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


def test_route_returns_404_when_simulation_missing() -> None:
    session = _FakeSession(sim=None)
    with pytest.raises(HTTPException) as exc:
        _call_route(session=session)
    assert exc.value.status_code == 404


def test_route_handles_empty_summaries() -> None:
    response = _call_route(format="json")

    body = json.loads(_body(response).decode("utf-8"))
    payload = body["cluster_run_summaries"]
    assert payload["total_clusters"] == 0
    assert payload["rows"] == []


def test_route_registered() -> None:
    from app.api.v1 import simulations as sim_mod

    path = "/simulations/{simulation_id}/cluster-run-summaries/export"
    paths = {r.path for r in sim_mod.router.routes}
    assert path in paths

    methods_by_path: dict[str, set[str]] = {}
    for r in sim_mod.router.routes:
        methods_by_path.setdefault(r.path, set()).update(r.methods or set())
    assert "GET" in methods_by_path[path]

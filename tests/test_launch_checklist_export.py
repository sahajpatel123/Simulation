"""Tests for the launch-checklist export serializers and route."""
from __future__ import annotations

import json
import sys
import types
import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.simulation.launch_checklist import build_launch_checklist
from app.simulation.launch_checklist_export import (
    launch_checklist_to_csv,
    launch_checklist_to_json,
    launch_checklist_to_markdown,
)


if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _registry(count: int = 52) -> list[dict[str, Any]]:
    return [
        {
            "cluster_id": f"cluster_{i}",
            "name": f"Cluster {i}",
            "population_weight": 1.0 / count,
        }
        for i in range(count)
    ]


def _results(**overrides: Any) -> dict[str, Any]:
    payload = {
        "population_weighted_conversion": 0.04,
        "product_type_detected": "saas",
        "cluster_breakdown": {
            "metro_power_professional": 0.06,
            "tier3_first_time_app_user": 0.03,
        },
        "raw_funnel": {
            "ARRIVE": 1000,
            "BROWSE": 600,
            "CONSIDER": 300,
            "DECIDE": 120,
            "PURCHASE": 40,
        },
        "domain_findings": [
            {"id": "f1", "title": "Support burden", "severity": "MAJOR"}
        ],
    }
    payload.update(overrides)
    return payload


def _checklist() -> Any:
    registry = _registry()
    return build_launch_checklist(
        _results(
            cluster_breakdown={item["cluster_id"]: 1.0 / 52 for item in registry}
        ),
        simulation_id=1,
        project_id=10,
        status="COMPLETED",
        signal_quality=0.85,
        visible_assumption_count=4,
        product_type="saas",
        cluster_registry=registry,
    )


def test_csv_has_summary_items_and_recommendations() -> None:
    csv_text = launch_checklist_to_csv(
        _checklist(),
        metadata={
            "generated_at": "2026-08-08T00:00:00Z",
            "user_id": 42,
            "format_version": "1",
            "simulation_id": 1,
            "project_id": 10,
        },
    )

    assert "Launch Readiness Summary" in csv_text
    assert "Checklist Items" in csv_text
    assert "Recommendations" in csv_text
    assert "results_present" in csv_text
    assert "readiness_score" in csv_text
    assert "Signals look launch-actionable" in csv_text


def test_csv_neutralises_formula_injection() -> None:
    checklist = _checklist()
    checklist.recommendations = ["=HYPERLINK('http://evil')"]

    csv_text = launch_checklist_to_csv(checklist)

    assert "'=HYPERLINK" in csv_text


def test_json_round_trips_payload() -> None:
    json_text = launch_checklist_to_json(
        _checklist(),
        metadata={"format_version": "1"},
    )
    payload = json.loads(json_text)

    assert payload["metadata"]["format_version"] == "1"
    assert payload["launch_checklist"]["simulation_id"] == 1
    assert payload["launch_checklist"]["project_id"] == 10
    assert payload["launch_checklist"]["verdict"] == "READY"


def test_markdown_includes_summary_items_and_recommendations() -> None:
    md = launch_checklist_to_markdown(
        _checklist(),
        simulation_id=1,
        project_id=10,
        project_name="Test Project",
        metadata={"generated_at": "2026-08-08T00:00:00Z"},
    )

    assert "# Test Project — Launch Readiness Checklist" in md
    assert "## Summary" in md
    assert "## Checklist" in md
    assert "## Recommendations" in md
    assert "results_present" in md
    assert "Simulation 1" in md
    assert "Project 10" in md


def test_markdown_escapes_pipe_characters() -> None:
    checklist = _checklist()
    checklist.items[0].label = "Results | payload"

    md = launch_checklist_to_markdown(checklist)

    assert "Results \\| payload" in md


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
        self.error_message = error_message
        self.signal_quality = 0.85
        self.results_json = results if results is not None else _results()


class _FakeProject:
    def __init__(self) -> None:
        self.id = 10
        self.title = "Test Project"


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


class _FakeAssumption:
    def __init__(self, text: str) -> None:
        self.text = text
        self.sensitivity = "MEDIUM"
        self.impact_score = 5.0


class _FakeSession:
    def __init__(
        self,
        sim: object | None = None,
        assumptions: list | None = None,
    ) -> None:
        self.sim = sim
        self.assumptions = assumptions

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Simulation":
            return _FakeQuery([self.sim] if self.sim is not None else [])
        if name == "Assumption":
            return _FakeQuery(self.assumptions or [])
        if name == "Project":
            return _FakeQuery([_FakeProject()])
        return _FakeQuery([])


def _call_route(
    session: _FakeSession | None = None,
    *,
    format: str = "csv",
):
    from app.api.v1 import simulations as sim_mod

    db = session if session is not None else _FakeSession(_FakeSimulation())
    return sim_mod.export_launch_checklist(
        simulation_id=1,
        format=format,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _stream_bytes(response: Any) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_route_returns_csv_export() -> None:
    response = _call_route(
        _FakeSession(_FakeSimulation(), assumptions=[_FakeAssumption("viral loop")]),
        format="csv",
    )

    assert response.headers["content-type"].startswith("text/csv")
    assert "launch-checklist-1.csv" in response.headers["content-disposition"]
    body = asyncio.run(_stream_bytes(response)).decode("utf-8")
    assert "Launch Readiness Summary" in body


def test_route_returns_json_export() -> None:
    response = _call_route(
        _FakeSession(_FakeSimulation(), assumptions=[_FakeAssumption("viral loop")]),
        format="json",
    )

    assert response.headers["content-type"].startswith("application/json")
    body = json.loads(asyncio.run(_stream_bytes(response)).decode("utf-8"))
    assert body["launch_checklist"]["simulation_id"] == 1


def test_route_returns_markdown_export() -> None:
    response = _call_route(
        _FakeSession(_FakeSimulation(), assumptions=[_FakeAssumption("viral loop")]),
        format="md",
    )

    assert response.headers["content-type"].startswith("text/markdown")
    body = asyncio.run(_stream_bytes(response)).decode("utf-8")
    assert "Test Project — Launch Readiness Checklist" in body


def test_route_rejects_non_completed_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="PENDING"))
    with pytest.raises(HTTPException) as exc:
        _call_route(session, format="csv")
    assert exc.value.status_code == 409


def test_route_rejects_failed_simulation() -> None:
    session = _FakeSession(
        _FakeSimulation(status="FAILED", error_message="boom")
    )
    with pytest.raises(HTTPException) as exc:
        _call_route(session, format="csv")
    assert exc.value.status_code == 422

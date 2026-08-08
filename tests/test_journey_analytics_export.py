"""Tests for the journey-analytics export helpers and route.

Covers the multi-section CSV rendering, the JSON envelope, spreadsheet
formula-injection guarding, malformed-payload resilience, and the
``GET /api/v1/simulations/{id}/journey/export`` route gates.
"""

from __future__ import annotations

import asyncio
import json
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

from app.simulation.journey_analytics_export import (  # noqa: E402
    FORMAT_VERSION,
    journey_analytics_to_csv,
    journey_analytics_to_json,
)


def _payload() -> dict:
    return {
        "simulation_id": 1,
        "project_id": 10,
        "status": "COMPLETED",
        "purchase_probability": 0.060933,
        "abandon_probability": 0.939067,
        "expected_steps_to_absorb": 2.7798,
        "expected_revisits": 0.12,
        "exit_stage_distribution": {
            "ARRIVE": 0.1,
            "BROWSE": 0.5,
            "CONSIDER": 0.25,
            "DECIDE": 0.089,
        },
        "top_paths": [
            {
                "path": ["ARRIVE", "BROWSE", "ABANDON"],
                "probability": 0.374833,
                "converted": False,
            },
            {
                "path": ["ARRIVE", "BROWSE", "CONSIDER", "DECIDE", "PURCHASE"],
                "probability": 0.040245,
                "converted": True,
            },
        ],
        "leverage_rankings": [
            {
                "from_state": "DECIDE",
                "to_state": "PURCHASE",
                "gain_per_5pp": 0.012,
                "relative_gain_pct": 19.7,
                "description": "Improving DECIDE→PURCHASE by 5pp lifts conversion.",
            }
        ],
        "per_cluster": [
            {
                "cluster_id": "c0",
                "purchase_probability": 0.08,
                "expected_steps_to_absorb": 3.1,
                "primary_exit_stage": "BROWSE",
                "exit_stage_distribution": {
                    "ARRIVE": 0.01,
                    "BROWSE": 0.6,
                    "CONSIDER": 0.2,
                    "DECIDE": 0.1,
                },
                "expected_visits_by_stage": {
                    "ARRIVE": 1.0,
                    "BROWSE": 1.1,
                    "CONSIDER": 0.5,
                    "DECIDE": 0.3,
                    "RETURN": 0.0,
                },
            }
        ],
        "key_insights": [
            "60.0% of simulated consumers exit at BROWSE — the largest leak.",
            "The most common journey is ARRIVE → BROWSE → ABANDON (37.5%).",
        ],
        "meta": {"matrix_count": 1, "weighted": True},
    }


def test_csv_renders_metadata_and_headline_sections() -> None:
    csv_text = journey_analytics_to_csv(
        _payload(),
        metadata={
            "generated_at": "2026-08-08T12:00:00+00:00",
            "user_id": 42,
            "simulation_id": 1,
            "project_id": 10,
        },
    )

    assert csv_text.startswith("generated_at,")
    assert "simulation_id,1" in csv_text
    assert "project_id,10" in csv_text
    assert "section,Headline" in csv_text
    assert "purchase_probability,0.060933" in csv_text
    assert "abandon_probability,0.939067" in csv_text
    assert "matrix_count,1" in csv_text
    assert "weighted,true" in csv_text


def test_csv_renders_all_founder_sections() -> None:
    csv_text = journey_analytics_to_csv(_payload())

    assert "section,Exit Stage Distribution" in csv_text
    assert "BROWSE,0.5" in csv_text
    assert "section,Top Paths" in csv_text
    assert "ARRIVE -> BROWSE -> ABANDON" in csv_text
    assert "0.374833" in csv_text
    assert "section,Leverage Rankings" in csv_text
    assert "DECIDE,PURCHASE" in csv_text
    assert "Improving DECIDE→PURCHASE" in csv_text
    assert "section,Per-Cluster" in csv_text
    assert "c0,0.08" in csv_text
    assert (
        "c0,0.08,3.1,BROWSE,0.01,0.6,0.2,0.1,1.0,1.1,0.5,0.3,0.0"
        in csv_text
    )
    assert "section,Key Insights" in csv_text
    assert "60.0% of simulated consumers exit at BROWSE" in csv_text


def test_csv_guards_spreadsheet_formula_injection() -> None:
    payload = _payload()
    payload["key_insights"] = ["=HYPERLINK(\"https://evil.example\")"]
    payload["per_cluster"][0]["primary_exit_stage"] = " \t+SUM(A1:A2)"

    csv_text = journey_analytics_to_csv(payload)

    assert "'=HYPERLINK" in csv_text
    assert "' \t+SUM(A1:A2)" in csv_text


def test_csv_handles_malformed_payload_without_raising() -> None:
    csv_text = journey_analytics_to_csv(
        {
            "purchase_probability": float("nan"),
            "exit_stage_distribution": "junk",
            "top_paths": ["not-a-dict"],
            "leverage_rankings": [None],
            "per_cluster": [{"cluster_id": "c0"}],
            "key_insights": None,
            "meta": None,
        }
    )

    assert "section,Headline" in csv_text
    assert "purchase_probability,0.0" in csv_text
    assert "section,Exit Stage Distribution" in csv_text
    assert "section,Top Paths" in csv_text
    assert "section,Per-Cluster" in csv_text
    assert "section,Key Insights" in csv_text


def test_json_renders_envelope_with_payload() -> None:
    text = journey_analytics_to_json(_payload(), metadata={"format_version": FORMAT_VERSION})
    data = json.loads(text)

    assert data["metadata"]["format_version"] == "1"
    assert data["journey_analytics"]["purchase_probability"] == pytest.approx(0.060933)
    assert data["journey_analytics"]["per_cluster"][0]["cluster_id"] == "c0"
    assert text.endswith("\n")


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
        self.results_json = results if results is not None else {
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


class _FakeQuery:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class _FakeSession:
    def __init__(self, sim: _FakeSimulation | None = None) -> None:
        self.sim = sim or _FakeSimulation()

    def query(self, *args, **kwargs):
        return _FakeQuery([self.sim])


def _user() -> object:
    return type("U", (), {"id": 42})()


async def _body_bytes(response: object) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _call_export(
    *,
    simulation_id: int = 1,
    format: str = "csv",
    session: _FakeSession | None = None,
):
    from app.api.v1 import simulations as sim_mod

    return sim_mod.export_simulation_journey_analytics(
        simulation_id=simulation_id,
        format=format,
        db=session or _FakeSession(),
        current_user=_user(),
    )


def test_export_route_returns_csv_attachment() -> None:
    response = _call_export()
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-analytics.csv"'
    )
    assert "section,Headline" in body
    assert "purchase_probability" in body
    assert "ARRIVE -> BROWSE -> ABANDON" in body


def test_export_route_returns_json_attachment() -> None:
    response = _call_export(format="json")
    body = asyncio.run(_body_bytes(response)).decode()
    data = json.loads(body)

    assert response.media_type == "application/json; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="journey-analytics.json"'
    )
    assert data["journey_analytics"]["simulation_id"] == 1
    assert data["metadata"]["user_id"] == 42


def test_export_route_rejects_unsupported_format() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_export(format="xml")
    assert exc.value.status_code == 400
    assert "expected 'csv' or 'json'" in exc.value.detail


def test_export_route_rejects_unsupported_format_before_ownership_lookup() -> None:
    # A malformed format is a client error regardless of the simulation's
    # existence/state, so the route must not touch the DB first.
    session = _FakeSession(_FakeSimulation(sim_id=999))
    session.sim = None
    with pytest.raises(HTTPException) as exc:
        _call_export(simulation_id=999, format="xml", session=session)
    assert exc.value.status_code == 400
    assert "expected 'csv' or 'json'" in exc.value.detail


def test_export_route_gates_failed_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="FAILED", error_message="boom"))
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session)
    assert exc.value.status_code == 422
    assert "boom" in exc.value.detail


def test_export_route_gates_running_simulation() -> None:
    session = _FakeSession(_FakeSimulation(status="RUNNING"))
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session)
    assert exc.value.status_code == 409
    assert "RUNNING" in exc.value.detail


def test_export_route_gates_empty_results() -> None:
    session = _FakeSession(_FakeSimulation(status="COMPLETED", results={}))
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session)
    assert exc.value.status_code == 422


def test_export_route_gates_missing_journey_data() -> None:
    session = _FakeSession(
        _FakeSimulation(
            results={
                "cluster_breakdown": {"c0": 0.04},
                "raw_funnel": {"conversion_rate": 0.04},
            }
        )
    )
    with pytest.raises(HTTPException) as exc:
        _call_export(session=session)
    assert exc.value.status_code == 404
    assert "Re-run the simulation" in exc.value.detail


def test_export_route_gates_missing_owned_simulation() -> None:
    session = _FakeSession(_FakeSimulation(sim_id=999))
    session.sim = None
    with pytest.raises(HTTPException) as exc:
        _call_export(simulation_id=999, session=session)
    assert exc.value.status_code == 404
    assert "Simulation not found" in exc.value.detail

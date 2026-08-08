"""
Tests that ``GET /simulations/{id}/results`` surfaces the conductor execution
diagnostics persisted by the worker as a first-class response field.

The diagnostics feature added a ``conductor_diagnostics`` key to the persisted
results blob; this module pins the API contract so the frontend can read the
typed field instead of digging through the raw ``results`` dict, and so legacy
results (persisted before the feature) still return an empty object.
"""
from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from typing import Any

from app.simulation.clusters.registry import ClusterRegistry

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.executed: list[tuple[Any, Any]] = []

    def execute(self, sql: Any, params: Any = None) -> _FakeRows:
        self.executed.append((sql, params))
        return _FakeRows([])

    def commit(self) -> None:
        self.commits += 1


class _FakeSimulation:
    def __init__(self, results_json: dict[str, Any]) -> None:
        self.id = 1
        self.project_id = 10
        self.status = "COMPLETED"
        self.consumer_volume = 10_000
        self.results_json = results_json
        self.error_message: str | None = None
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.signal_quality = 0.62


def _results_with_diagnostics() -> dict[str, Any]:
    cid = ClusterRegistry().all_clusters()[0].cluster_id
    diagnostics = {
        "architect_stats": [
            {
                "architect_name": "PricingArchitect",
                "attempted_clusters": 52,
                "completed_clusters": 52,
                "failed_clusters": 0,
                "first_failed_cluster": None,
                "severity_counts": {"CRITICAL": 4, "INFO": 36, "WARNING": 12},
            }
        ],
        "total_compute_failures": 0,
        "architects_with_failures": 0,
        "report_failures": 0,
        "failed_report_architects": [],
    }
    return {
        "mean_conversion_rate": 0.0312,
        "cluster_breakdown": {cid: 0.0312},
        "conductor_diagnostics": diagnostics,
    }


def test_results_endpoint_maps_diagnostics_from_persisted_blob(
    monkeypatch: Any,
) -> None:
    import app.api.v1.simulations as sim_mod

    results = _results_with_diagnostics()
    sim = _FakeSimulation(results)
    session = _FakeSession()
    monkeypatch.setattr(
        sim_mod,
        "_get_owned_simulation",
        lambda simulation_id, user_id, db: sim,
    )

    out = sim_mod.get_simulation_results(
        simulation_id=sim.id,
        db=session,
        current_user=types.SimpleNamespace(id=7),
    )

    assert out.conductor_diagnostics == results["conductor_diagnostics"]
    assert out.results == results
    cid = next(iter(results["cluster_breakdown"]))
    assert out.cluster_breakdown[0]["cluster_id"] == cid


def test_results_endpoint_returns_empty_diagnostics_for_legacy_runs(
    monkeypatch: Any,
) -> None:
    import app.api.v1.simulations as sim_mod

    sim = _FakeSimulation({"mean_conversion_rate": 0.0312})
    session = _FakeSession()
    monkeypatch.setattr(
        sim_mod,
        "_get_owned_simulation",
        lambda simulation_id, user_id, db: sim,
    )

    out = sim_mod.get_simulation_results(
        simulation_id=sim.id,
        db=session,
        current_user=types.SimpleNamespace(id=7),
    )

    assert out.conductor_diagnostics == {}

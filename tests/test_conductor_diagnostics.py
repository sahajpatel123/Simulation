"""
Tests for conductor execution diagnostics.

The Conductor previously absorbed architect ``compute()`` and
``generate_report()`` exceptions with a log line only: a broken architect
silently degraded the simulation with zero trace in the persisted result.
This module pins the new deterministic diagnostics block:

* per-architect attempted/completed/failed cluster counts,
* the severity distribution of completed outputs,
* the first cluster where a compute failure occurred,
* cross-architect report-failure accounting.
"""
from __future__ import annotations

import json
from typing import Any

from app.simulation.architects.base import ArchitectOutput
from app.simulation.architects.pricing import PricingArchitect
from app.simulation.clusters.registry import ClusterRegistry
from app.simulation.conductor import (
    _ARCHITECTS,
    ArchitectDiagnostics,
    Conductor,
    ConductorDiagnostics,
)
from app.simulation.product_type import ProductType


def _output(severity: str = "INFO") -> ArchitectOutput:
    return ArchitectOutput(
        architect_name="PricingArchitect",
        cluster_id="some_cluster",
        metrics={"price_fit_score": 0.8},
        flags={"expensive": False},
        narrative_findings=["ok"],
        severity=severity,
    )


class FailingComputeArchitect(PricingArchitect):
    """Compute always raises — used to verify failure accounting."""

    def compute(
        self,
        cluster: Any,
        agent_profile: dict[str, Any],
        assumptions: list[dict[str, Any]],
        env_params: dict[str, Any],
    ) -> ArchitectOutput:
        raise RuntimeError("diagnostics test compute failure")


class FailingReportArchitect(PricingArchitect):
    """Cross-cluster report always raises — used to verify report accounting."""

    def generate_report(self, outputs: list[ArchitectOutput]) -> Any:
        raise RuntimeError("diagnostics test report failure")


# ---------------------------------------------------------------------------
# Unit: per-architect accounting
# ---------------------------------------------------------------------------


def test_record_success_counts_severity() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output("WARNING"))
    stats.record_success(_output("CRITICAL"))
    stats.record_success(_output("info"))

    assert stats.attempted_clusters == 3
    assert stats.completed_clusters == 3
    assert stats.failed_clusters == 0
    assert stats.first_failed_cluster is None
    assert stats.severity_counts["INFO"] == 1
    assert stats.severity_counts["WARNING"] == 1
    assert stats.severity_counts["CRITICAL"] == 1


def test_record_failure_records_first_cluster_only() -> None:
    stats = ArchitectDiagnostics(architect_name="TrustArchitect")
    stats.record_failure("cluster_a")
    stats.record_failure("cluster_b")

    assert stats.attempted_clusters == 2
    assert stats.completed_clusters == 0
    assert stats.failed_clusters == 2
    assert stats.first_failed_cluster == "cluster_a"


def test_architect_diagnostics_to_dict_is_deterministic() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output("WARNING"))
    stats.record_failure("cluster_a")

    payload = stats.to_dict()
    assert payload == {
        "architect_name": "PricingArchitect",
        "attempted_clusters": 2,
        "completed_clusters": 1,
        "failed_clusters": 1,
        "first_failed_cluster": "cluster_a",
        "severity_counts": {"CRITICAL": 0, "INFO": 0, "WARNING": 1},
    }
    # Calling twice must not mutate or reorder the payload.
    assert stats.to_dict() == payload


def test_conductor_diagnostics_rolls_up_and_sorts() -> None:
    beta = ArchitectDiagnostics(architect_name="BetaArchitect")
    alpha = ArchitectDiagnostics(architect_name="AlphaArchitect")
    alpha.record_failure("c1")
    beta.record_success(_output("CRITICAL"))

    diagnostics = ConductorDiagnostics(architect_stats=[beta, alpha])
    diagnostics.report_failures = 1
    diagnostics.failed_report_architects = ["ZetaArchitect", "AlphaArchitect"]

    payload = diagnostics.to_dict()
    assert [s["architect_name"] for s in payload["architect_stats"]] == [
        "AlphaArchitect",
        "BetaArchitect",
    ]
    assert payload["total_compute_failures"] == 1
    assert payload["architects_with_failures"] == 1
    assert payload["report_failures"] == 1
    assert payload["failed_report_architects"] == [
        "AlphaArchitect",
        "ZetaArchitect",
    ]


# ---------------------------------------------------------------------------
# Integration: Conductor.run records coverage and failures
# ---------------------------------------------------------------------------


def _run_conductor(conductor: Conductor) -> Any:
    return conductor.run(
        agents=[],
        env_params={
            "average_order_value": 999,
            "description": "A saas crm dashboard",
        },
        assumptions=[],
        product_type=ProductType.SAAS,
    )


def test_run_records_full_coverage_per_architect() -> None:
    result = _run_conductor(Conductor())
    payload = result.diagnostics.to_dict()

    assert payload["total_compute_failures"] == 0
    assert payload["architects_with_failures"] == 0
    assert payload["report_failures"] == 0
    assert payload["failed_report_architects"] == []

    by_name = {s["architect_name"]: s for s in payload["architect_stats"]}
    pricing = by_name["PricingArchitect"]
    assert pricing["attempted_clusters"] == 52
    assert pricing["completed_clusters"] == 52
    assert pricing["failed_clusters"] == 0
    assert pricing["first_failed_cluster"] is None
    assert sum(pricing["severity_counts"].values()) == 52


def test_run_records_compute_timing_for_every_architect() -> None:
    result = _run_conductor(Conductor())
    payload = result.diagnostics.timing_to_dict()

    assert payload["compute_calls"] > 0
    assert payload["total_ms"] >= 0.0
    assert payload["slowest_architect"] in {
        row["architect_name"] for row in payload["architects"]
    }
    by_name = {row["architect_name"]: row for row in payload["architects"]}
    pricing = by_name["PricingArchitect"]
    assert pricing["compute_calls"] == 52
    assert pricing["total_ms"] >= 0.0
    assert pricing["p50_ms"] is not None
    assert pricing["p95_ms"] is not None
    assert pricing["max_ms"] is not None
    # The timing payload must never leak into the fingerprinted diagnostics.
    assert "total_ms" not in result.diagnostics.to_dict()["architect_stats"][0]


def test_run_counts_compute_failures_and_first_cluster(
    monkeypatch: Any,
) -> None:
    monkeypatch.setitem(_ARCHITECTS, "PricingArchitect", FailingComputeArchitect())
    result = _run_conductor(Conductor())
    payload = result.diagnostics.to_dict()

    by_name = {s["architect_name"]: s for s in payload["architect_stats"]}
    pricing = by_name["PricingArchitect"]
    assert pricing["attempted_clusters"] == 52
    assert pricing["completed_clusters"] == 0
    assert pricing["failed_clusters"] == 52
    assert pricing["first_failed_cluster"] == ClusterRegistry().all_clusters()[0].cluster_id
    assert payload["total_compute_failures"] == 52
    assert payload["architects_with_failures"] == 1


def test_run_counts_report_failures(monkeypatch: Any) -> None:
    monkeypatch.setitem(_ARCHITECTS, "PricingArchitect", FailingReportArchitect())
    result = _run_conductor(Conductor())
    payload = result.diagnostics.to_dict()

    assert payload["report_failures"] == 1
    assert payload["failed_report_architects"] == ["PricingArchitect"]
    # Compute itself still succeeded for every cluster.
    by_name = {s["architect_name"]: s for s in payload["architect_stats"]}
    assert by_name["PricingArchitect"]["completed_clusters"] == 52


# ---------------------------------------------------------------------------
# Persistence contract: the payload is JSON-safe, deterministic, and wired
# into both the result schema and the worker's persisted results blob.
# ---------------------------------------------------------------------------


def test_diagnostics_payload_is_json_safe_and_stable() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output("CRITICAL"))
    stats.record_failure("cluster_a")
    diagnostics = ConductorDiagnostics(architect_stats=[stats])
    diagnostics.report_failures = 1
    diagnostics.failed_report_architects = ["PricingArchitect"]

    first = diagnostics.to_dict()
    # The persisted results_json is a PostgreSQL JSONB blob, so the payload
    # must round-trip through JSON without loss or reordering.
    round_tripped = json.loads(json.dumps(first))
    assert round_tripped == first
    assert diagnostics.to_dict() == first


def test_result_schema_surfaces_diagnostics_and_defaults_for_legacy_runs() -> None:
    from app.schemas.simulation import SimulationResultOut

    created_at = "2026-01-01T00:00:00Z"
    legacy = SimulationResultOut(
        id=1,
        project_id=1,
        status="COMPLETED",
        consumer_volume=10_000,
        results={"mean_conversion_rate": 0.12},
        error_message=None,
        created_at=created_at,
        updated_at=created_at,
    )
    assert legacy.conductor_diagnostics == {}

    payload = {
        "architect_stats": [],
        "total_compute_failures": 0,
        "architects_with_failures": 0,
        "report_failures": 0,
        "failed_report_architects": [],
    }
    with_diagnostics = SimulationResultOut(
        id=2,
        project_id=1,
        status="COMPLETED",
        consumer_volume=10_000,
        results={},
        error_message=None,
        created_at=created_at,
        updated_at=created_at,
        conductor_diagnostics=payload,
    )
    assert with_diagnostics.conductor_diagnostics == payload


def test_worker_wires_diagnostics_into_persisted_results() -> None:
    from pathlib import Path

    source = Path("backend/app/tasks/simulation_tasks.py").read_text()
    assert (
        'results_dict["conductor_diagnostics"] = '
        "conductor_result.diagnostics.to_dict()"
    ) in source
    # The diagnostics must be part of the fingerprint so a run whose
    # execution health changed is never reported as an exact replay.
    assert "results_fingerprint = stable_result_fingerprint(results_dict)" in source

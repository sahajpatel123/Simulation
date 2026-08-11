"""Tests for per-architect conductor compute-timing observability.

The pipeline-timing feature reports wall-clock time at the *stage* level
(agent-profile generation, conductor, accountability/funnel, aggregation).
This feature adds the missing granularity inside the conductor: how long each
domain architect's ``compute()`` took across the clusters it evaluated, so an
operator can see which architect dominates a simulation's wall clock.

The feature has four moving parts:

1. ``ArchitectDiagnostics`` records per-``compute()`` wall-clock durations and
   rolls them into total / mean / p50 / p95 / max milliseconds.
2. ``ConductorDiagnostics.timing_to_dict`` aggregates the per-architect rows,
   totals, and the slowest architect.
3. The Celery worker persists ``results_json["conductor_architect_timing"]``
   after the reproducibility fingerprint is computed, and the fingerprint
   layer treats the key as volatile so identical-input replays still match.
4. The results API surfaces the payload as
   ``SimulationResultOut.conductor_architect_timing``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.simulation import SimulationResultOut
from app.simulation.architects.base import ArchitectOutput
from app.simulation.conductor import (
    ConductorDiagnostics,
    ArchitectDiagnostics,
)
from app.simulation.reproducibility import (
    VOLATILE_RESULT_KEYS,
    stable_result_fingerprint,
)

_ROOT = Path(__file__).resolve().parents[1]
_TASKS_PATH = _ROOT / "backend" / "app" / "tasks" / "simulation_tasks.py"
_ROUTE_PATH = _ROOT / "backend" / "app" / "api" / "v1" / "simulations.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _output(severity: str = "INFO") -> ArchitectOutput:
    return ArchitectOutput(
        architect_name="PricingArchitect",
        cluster_id="some_cluster",
        metrics={"price_fit_score": 0.8},
        flags={"expensive": False},
        narrative_findings=["ok"],
        severity=severity,
    )


# ── Recording behaviour ─────────────────────────────────────────────────────


def test_record_success_records_finite_durations_only() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output(), duration_ms=1.5)
    stats.record_success(_output(), duration_ms=3.0)
    stats.record_success(_output(), duration_ms=-1.0)
    stats.record_success(_output(), duration_ms=float("nan"))
    stats.record_success(_output(), duration_ms=float("inf"))
    stats.record_success(_output(), duration_ms="nope")  # type: ignore[arg-type]
    stats.record_success(_output())  # legacy call without a duration

    assert stats.compute_durations_ms == [1.5, 3.0]
    assert stats.completed_clusters == 7


def test_record_success_keeps_deterministic_diagnostics_unchanged() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output("WARNING"), duration_ms=2.5)
    stats.record_success(_output("CRITICAL"), duration_ms=4.0)

    assert stats.to_dict() == {
        "architect_name": "PricingArchitect",
        "attempted_clusters": 2,
        "completed_clusters": 2,
        "failed_clusters": 0,
        "first_failed_cluster": None,
        "severity_counts": {"CRITICAL": 1, "INFO": 0, "WARNING": 1},
    }


def test_architect_timing_to_dict_rolls_up_percentiles() -> None:
    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    for ms in (1.0, 2.0, 3.0, 4.0, 100.0):
        stats.record_success(_output(), duration_ms=ms)

    payload = stats.timing_to_dict()
    assert payload == {
        "architect_name": "PricingArchitect",
        "compute_calls": 5,
        "total_ms": 110.0,
        "mean_ms": 22.0,
        "p50_ms": 3.0,
        "p95_ms": 100.0,
        "max_ms": 100.0,
    }


def test_architect_timing_to_dict_handles_no_durations() -> None:
    payload = ArchitectDiagnostics(
        architect_name="RunwayArchitect"
    ).timing_to_dict()
    assert payload == {
        "architect_name": "RunwayArchitect",
        "compute_calls": 0,
        "total_ms": 0.0,
        "mean_ms": None,
        "p50_ms": None,
        "p95_ms": None,
        "max_ms": None,
    }


def test_conductor_timing_to_dict_sorts_aggregates_and_picks_slowest() -> None:
    beta = ArchitectDiagnostics(architect_name="BetaArchitect")
    beta.record_success(_output(), duration_ms=5.0)
    alpha = ArchitectDiagnostics(architect_name="AlphaArchitect")
    alpha.record_success(_output(), duration_ms=10.0)
    alpha.record_success(_output(), duration_ms=20.0)
    untimed = ArchitectDiagnostics(architect_name="UntimedArchitect")

    payload = ConductorDiagnostics(
        architect_stats=[untimed, beta, alpha]
    ).timing_to_dict()
    assert [row["architect_name"] for row in payload["architects"]] == [
        "AlphaArchitect",
        "BetaArchitect",
    ]
    assert payload["compute_calls"] == 3
    assert payload["total_ms"] == 35.0
    assert payload["mean_ms"] == round(35.0 / 3.0, 4)
    assert payload["slowest_architect"] == "AlphaArchitect"
    assert payload["slowest_architect_total_ms"] == 30.0


def test_conductor_timing_to_dict_handles_no_timed_architects() -> None:
    payload = ConductorDiagnostics().timing_to_dict()
    assert payload == {
        "architects": [],
        "compute_calls": 0,
        "total_ms": 0.0,
        "mean_ms": None,
        "slowest_architect": None,
        "slowest_architect_total_ms": None,
    }


def test_timing_payload_is_json_safe() -> None:
    import json

    stats = ArchitectDiagnostics(architect_name="PricingArchitect")
    stats.record_success(_output(), duration_ms=1.25)
    stats.record_success(_output(), duration_ms=2.75)
    payload = ConductorDiagnostics(architect_stats=[stats]).timing_to_dict()

    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped == payload


# ── Reproducibility fingerprint ─────────────────────────────────────────────


def test_conductor_architect_timing_is_volatile_for_fingerprinting() -> None:
    assert "conductor_architect_timing" in VOLATILE_RESULT_KEYS
    base = {"conversion_rate": 0.05, "conductor_diagnostics": {"report_failures": 0}}
    with_timing = {
        **base,
        "conductor_architect_timing": {
            "architects": [
                {
                    "architect_name": "PricingArchitect",
                    "compute_calls": 52,
                    "total_ms": 41.9,
                }
            ],
            "compute_calls": 52,
            "total_ms": 41.9,
            "slowest_architect": "PricingArchitect",
        },
    }
    assert stable_result_fingerprint(base) == stable_result_fingerprint(with_timing)


# ── Worker wiring ───────────────────────────────────────────────────────────


def test_worker_persists_architect_timing_after_fingerprint() -> None:
    source = _read(_TASKS_PATH)
    assert (
        'results_dict["conductor_architect_timing"] = (\n'
        "            conductor_result.diagnostics.timing_to_dict()\n"
        "        )" in source
    )
    fp_index = source.index("results_fingerprint = stable_result_fingerprint(results_dict)")
    timing_index = source.index('results_dict["conductor_architect_timing"] = (')
    assert fp_index < timing_index


# ── API contract ────────────────────────────────────────────────────────────


def test_results_schema_defaults_architect_timing_to_empty() -> None:
    legacy = SimulationResultOut(
        id=2,
        project_id=1,
        status="COMPLETED",
        consumer_volume=10_000,
        results={},
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert legacy.conductor_architect_timing == {}


def test_results_schema_accepts_architect_timing_payload() -> None:
    payload = {
        "architects": [
            {
                "architect_name": "PricingArchitect",
                "compute_calls": 52,
                "total_ms": 41.9,
                "mean_ms": 0.81,
                "p50_ms": 0.7,
                "p95_ms": 1.9,
                "max_ms": 4.2,
            }
        ],
        "compute_calls": 52,
        "total_ms": 41.9,
        "mean_ms": 0.81,
        "slowest_architect": "PricingArchitect",
        "slowest_architect_total_ms": 41.9,
    }
    out = SimulationResultOut(
        id=3,
        project_id=1,
        status="COMPLETED",
        consumer_volume=10_000,
        results={},
        error_message=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        conductor_architect_timing=payload,
    )
    assert out.conductor_architect_timing == payload


def test_results_schema_rejects_non_dict_architect_timing() -> None:
    with pytest.raises(ValidationError):
        SimulationResultOut(
            id=4,
            project_id=1,
            status="COMPLETED",
            consumer_volume=10_000,
            results={},
            error_message=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            conductor_architect_timing="not-a-dict",  # type: ignore[arg-type]
        )


def test_results_route_surfaces_architect_timing() -> None:
    source = _read(_ROUTE_PATH)
    assert (
        "conductor_architect_timing=results_json.get(" in source
        and '"conductor_architect_timing", {}' in source
    )

"""Tests for the per-stage simulation pipeline-timing observability feature.

The feature has four moving parts:

1. ``build_pipeline_timing`` normalises the worker's raw stage timers into
   a compact, finite-only payload with totals and per-agent scaling.
2. The Celery worker records each compute stage and persists the payload in
   ``results_json["pipeline_timing"]`` after the reproducibility fingerprint
   is computed.
3. The fingerprint layer treats ``pipeline_timing`` as volatile so
   identical-input replays still match despite wall-clock differences.
4. The results API surfaces the payload as ``SimulationResultOut.pipeline_timing``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.simulation import SimulationResultOut
from app.simulation.pipeline_timing import build_pipeline_timing
from app.simulation.reproducibility import (
    VOLATILE_RESULT_KEYS,
    stable_result_fingerprint,
)

_ROOT = Path(__file__).resolve().parents[1]
_TASKS_PATH = _ROOT / "backend" / "app" / "tasks" / "simulation_tasks.py"
_ROUTE_PATH = _ROOT / "backend" / "app" / "api" / "v1" / "simulations.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Helper behaviour ─────────────────────────────────────────────────────────


def test_build_pipeline_timing_rounds_and_sums_stages() -> None:
    payload = build_pipeline_timing(
        {
            "load_project_data": 0.123456,
            "agent_profile_generation": 1.0,
            "conductor_run": 42.0001,
        },
        total_agents=10_000,
    )
    assert payload["load_project_data"] == 0.1235
    assert payload["agent_profile_generation"] == 1.0
    assert payload["conductor_run"] == 42.0001
    assert payload["total_seconds"] == 43.1236
    assert payload["stage_count"] == 3
    assert payload["per_agent_ms"] == 4.31236


def test_build_pipeline_timing_drops_invalid_stages() -> None:
    payload = build_pipeline_timing(
        {
            "good": 0.5,
            "negative": -1.0,
            "nan": float("nan"),
            "inf": float("inf"),
            "bool": True,
            "text": "not-a-number",
            "": 1.0,
        }
    )
    assert payload == {
        "good": 0.5,
        "total_seconds": 0.5,
        "stage_count": 1,
        "per_agent_ms": None,
    }


def test_build_pipeline_timing_handles_empty_and_none_input() -> None:
    assert build_pipeline_timing(None) == {
        "total_seconds": 0.0,
        "stage_count": 0,
        "per_agent_ms": None,
    }
    assert build_pipeline_timing({}) == {
        "total_seconds": 0.0,
        "stage_count": 0,
        "per_agent_ms": None,
    }


def test_build_pipeline_timing_includes_end_to_end_when_valid() -> None:
    payload = build_pipeline_timing(
        {"conductor_run": 2.0},
        end_to_end_seconds=3.123456,
    )
    assert payload["end_to_end_seconds"] == 3.1235


def test_build_pipeline_timing_omits_invalid_end_to_end() -> None:
    for bad in (None, -0.1, float("nan"), "nope"):
        payload = build_pipeline_timing({}, end_to_end_seconds=bad)  # type: ignore[arg-type]
        assert "end_to_end_seconds" not in payload


def test_build_pipeline_timing_handles_agent_volume_edge_cases() -> None:
    zero_agents = build_pipeline_timing({"a": 1.0}, total_agents=0)
    none_agents = build_pipeline_timing({"a": 1.0}, total_agents=None)
    bool_agents = build_pipeline_timing({"a": 1.0}, total_agents=True)  # type: ignore[arg-type]
    assert zero_agents["per_agent_ms"] is None
    assert none_agents["per_agent_ms"] is None
    assert bool_agents["per_agent_ms"] is None


# ── Reproducibility fingerprint ──────────────────────────────────────────────


def test_pipeline_timing_is_volatile_for_fingerprinting() -> None:
    assert "pipeline_timing" in VOLATILE_RESULT_KEYS
    base = {"conversion_rate": 0.05, "conductor_diagnostics": {"report_failures": 0}}
    with_timing = {
        **base,
        "pipeline_timing": {
            "conductor_run": 41.9,
            "total_seconds": 42.0,
            "stage_count": 4,
        },
    }
    assert stable_result_fingerprint(base) == stable_result_fingerprint(with_timing)


# ── Worker wiring ────────────────────────────────────────────────────────────


def test_worker_persists_pipeline_timing_after_fingerprint() -> None:
    source = _read(_TASKS_PATH)
    assert 'results_dict["pipeline_timing"] = build_pipeline_timing(' in source
    fp_index = source.index("results_fingerprint = stable_result_fingerprint(results_dict)")
    timing_index = source.index('results_dict["pipeline_timing"] = build_pipeline_timing(')
    assert fp_index < timing_index
    assert "stage_timings[\"conductor_run\"] = wall_s" in source
    assert "stage_timings[\"agent_profile_generation\"]" in source
    assert "stage_timings[\"accountability_and_funnel\"]" in source


# ── API contract ─────────────────────────────────────────────────────────────


def test_results_schema_defaults_pipeline_timing_to_empty() -> None:
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
    assert legacy.pipeline_timing == {}


def test_results_schema_accepts_pipeline_timing_payload() -> None:
    payload = {
        "conductor_run": 41.9,
        "total_seconds": 42.0,
        "stage_count": 4,
        "per_agent_ms": 4.2,
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
        pipeline_timing=payload,
    )
    assert out.pipeline_timing == payload


def test_results_schema_rejects_non_dict_pipeline_timing() -> None:
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
            pipeline_timing="not-a-dict",  # type: ignore[arg-type]
        )


def test_results_route_surfaces_pipeline_timing() -> None:
    source = _read(_ROUTE_PATH)
    assert "pipeline_timing=results_json.get(\"pipeline_timing\", {})" in source

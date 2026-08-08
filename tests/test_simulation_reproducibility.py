"""Tests for reproducible, seeded simulation runs.

The feature has three moving parts:

1. ``POST /simulations`` accepts an optional ``seed`` and freezes a
   snapshot of the environment inputs at enqueue time.
2. The Celery worker prefers the frozen snapshot and the explicit seed,
   falling back to the live environment / legacy ``id * 37`` scheme for
   pre-feature runs.
3. ``POST /simulations/{id}/rerun`` queues an exact replay of a
   completed run (same environment snapshot + same seed) so founders can
   distinguish sampling noise from real input changes.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.simulation import SimulationCreate, SimulationStatusOut
from app.tasks.simulation_tasks import (
    build_environment_snapshot,
    resolve_run_environment,
    resolve_simulation_seed,
)

_ROOT = Path(__file__).resolve().parents[1]
_SIMULATIONS_PATH = _ROOT / "backend" / "app" / "api" / "v1" / "simulations.py"
_TASKS_PATH = _ROOT / "backend" / "app" / "tasks" / "simulation_tasks.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract(path: Path, func_name: str) -> str:
    source = _read(path)
    match = re.search(
        rf"def {func_name}\([\s\S]*?\n(?=\ndef |\nclass |\Z)",
        source,
    )
    assert match, f"{func_name} not found in {path.name}"
    return match.group(0)


def _fake_sim(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": 7,
        "project_id": 10,
        "environment_id": 3,
        "status": "COMPLETED",
        "consumer_volume": 10_000,
        "seed": None,
        "env_snapshot_json": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _fake_environment(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": 3,
        "project_id": 10,
        "mode": "MANUAL",
        "consumer_volume": 10_000,
        "growth_rate_per_month": 5.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
        "scenario_type": None,
        "manual_params_json": None,
        "trend_data_json": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── Schema ──────────────────────────────────────────────────────────────────


def test_simulation_create_seed_is_optional_and_nullable() -> None:
    assert SimulationCreate(project_id=1).seed is None
    assert SimulationCreate(project_id=1, seed=42).seed == 42
    assert SimulationCreate(project_id=1, seed=0).seed == 0


@pytest.mark.parametrize("bad_seed", [-1, 2_147_483_648])
def test_simulation_create_rejects_out_of_range_seed(bad_seed: int) -> None:
    with pytest.raises(ValidationError):
        SimulationCreate(project_id=1, seed=bad_seed)


def test_simulation_status_schema_exposes_seed() -> None:
    base = {
        "id": 1,
        "project_id": 1,
        "status": "QUEUED",
        "consumer_volume": 10_000,
        "task_id": None,
        "error_message": None,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    assert SimulationStatusOut(**base).seed is None
    assert SimulationStatusOut(**base, seed=42).seed == 42


# ── Seed resolution ─────────────────────────────────────────────────────────


def test_resolve_simulation_seed_prefers_explicit_seed() -> None:
    assert resolve_simulation_seed(42, 7) == 42
    assert resolve_simulation_seed(0, 7) == 0


def test_resolve_simulation_seed_falls_back_to_legacy_scheme() -> None:
    assert resolve_simulation_seed(None, 7) == 259
    assert resolve_simulation_seed(None, 1) == 37


# ── Environment snapshot ────────────────────────────────────────────────────


def test_build_environment_snapshot_uses_defaults_when_no_manual_params() -> None:
    env = _fake_environment()
    snapshot = build_environment_snapshot(env, consumer_volume=10_000)

    assert snapshot["scenario_type"] is None
    assert snapshot["base_env"] == {
        "consumer_volume": 10_000,
        "growth_rate_per_month": 5.0,
        "average_order_value": 999.0,
        "price_sensitivity": 0.5,
        "market_maturity": 0.3,
    }


def test_build_environment_snapshot_prefers_manual_params() -> None:
    env = _fake_environment(
        scenario_type="RECESSION",
        manual_params_json={"average_order_value": 499.0, "growth_rate_per_month": -2.0},
    )
    snapshot = build_environment_snapshot(env, consumer_volume=10_000)

    assert snapshot["scenario_type"] == "RECESSION"
    assert snapshot["base_env"] == {
        "average_order_value": 499.0,
        "growth_rate_per_month": -2.0,
    }


def test_resolve_run_environment_prefers_frozen_snapshot() -> None:
    sim = _fake_sim(
        consumer_volume=10_000,
        env_snapshot_json={
            "base_env": {"average_order_value": 700.0},
            "scenario_type": "HIGH_GROWTH",
        },
    )
    # The live environment has diverged since enqueue; it must be ignored.
    live = _fake_environment(
        scenario_type="SATURATED",
        manual_params_json={"average_order_value": 200.0},
    )

    base_env, scenario_type = resolve_run_environment(sim, live)
    assert base_env == {"average_order_value": 700.0}
    assert scenario_type == "HIGH_GROWTH"


def test_resolve_run_environment_falls_back_to_live_env_for_legacy_runs() -> None:
    sim = _fake_sim(consumer_volume=10_000, env_snapshot_json=None)
    live = _fake_environment(
        scenario_type="RECESSION",
        manual_params_json={"average_order_value": 599.0},
    )

    base_env, scenario_type = resolve_run_environment(sim, live)
    assert base_env == {"average_order_value": 599.0}
    assert scenario_type == "RECESSION"


def test_resolve_run_environment_ignores_malformed_snapshot_base_env() -> None:
    sim = _fake_sim(
        env_snapshot_json={
            "base_env": "not-a-dict",
            "scenario_type": "HIGH_GROWTH",
        }
    )
    live = _fake_environment(
        manual_params_json={"average_order_value": 599.0},
    )

    base_env, scenario_type = resolve_run_environment(sim, live)
    assert base_env == {}
    assert scenario_type == "HIGH_GROWTH"


# ── Rerun route contract ────────────────────────────────────────────────────


def test_rerun_route_declares_rate_limit() -> None:
    route_block = re.search(
        r"@router\.post\([\s\S]*?def rerun_simulation\(",
        _read(_SIMULATIONS_PATH),
    )
    assert route_block, "rerun_simulation route decorator not found"
    assert "Depends(rate_limit(" in route_block.group(0)


def test_rerun_locks_source_row_and_scopes_to_owner() -> None:
    block = _extract(_SIMULATIONS_PATH, "rerun_simulation")
    assert ".with_for_update()" in block
    assert "Project.user_id == current_user.id" in block


def test_rerun_requires_completed_source() -> None:
    block = _extract(_SIMULATIONS_PATH, "rerun_simulation")
    assert 'source.status != "COMPLETED"' in block
    assert "rerun requires completed results" in block


def test_rerun_clones_seed_and_environment_snapshot() -> None:
    block = _extract(_SIMULATIONS_PATH, "rerun_simulation")
    assert "resolve_simulation_seed(source.seed, source.id)" in block
    assert "copy.deepcopy(source.env_snapshot_json)" in block
    assert "build_environment_snapshot(environment, source.consumer_volume)" in block
    assert "seed=resolve_simulation_seed(source.seed, source.id)" in block
    assert "env_snapshot_json=env_snapshot" in block


def test_rerun_blocks_duplicate_in_flight_run() -> None:
    block = _extract(_SIMULATIONS_PATH, "rerun_simulation")
    assert 'Simulation.status.in_(["QUEUED", "RUNNING"])' in block
    assert "is already {running.status}" in block


def test_rerun_enqueues_and_busts_caches() -> None:
    block = _extract(_SIMULATIONS_PATH, "rerun_simulation")
    assert "run_full_simulation.delay(sim.id)" in block
    assert "_invalidate_simulation_caches(current_user.id)" in block


def test_create_simulation_persists_seed_and_snapshot() -> None:
    block = _extract(_SIMULATIONS_PATH, "create_simulation")
    assert "seed=payload.seed" in block
    assert "env_snapshot_json=build_environment_snapshot(" in block


# ── Worker wiring ───────────────────────────────────────────────────────────


def test_worker_uses_resolved_seed_and_frozen_snapshot() -> None:
    block = _extract(_TASKS_PATH, "run_full_simulation")
    assert "resolve_run_environment(sim, environment)" in block
    assert "seed=resolve_simulation_seed(sim.seed, simulation_id)" in block
    assert 'results_dict["seed_used"] = seed' in block


def test_migration_adds_seed_and_snapshot_columns() -> None:
    migration = _read(_ROOT / "migrate_and_start.py")
    assert '("seed", "INTEGER")' in migration
    assert '("env_snapshot_json", "JSONB")' in migration

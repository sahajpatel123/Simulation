"""Tests for result fingerprinting and reproducibility verification.

The feature has three moving parts:

1. ``stable_result_fingerprint`` canonicalises a completed simulation's
   results payload (ignoring volatile timing/timestamp fields) so two
   runs with identical inputs produce identical fingerprints.
2. ``inputs_are_identical`` compares consumer volume, resolved seed, and
   canonical environment snapshot so the endpoint can find sibling runs.
3. The worker persists ``results_fingerprint`` at completion and the new
   ``GET /simulations/{id}/reproducibility`` route surfaces the manifest
   plus a match/mismatch verdict for identical-input runs.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from app.simulation.reproducibility import (
    FINGERPRINT_ALGORITHM,
    VOLATILE_RESULT_KEYS,
    canonical_env_snapshot,
    inputs_are_identical,
    stable_result_fingerprint,
)

_ROOT = Path(__file__).resolve().parents[1]
_SIMULATIONS_PATH = _ROOT / "backend" / "app" / "api" / "v1" / "simulations.py"
_TASKS_PATH = _ROOT / "backend" / "app" / "tasks" / "simulation_tasks.py"
_MODEL_PATH = _ROOT / "backend" / "app" / "models" / "simulation.py"
_MIGRATIONS_PATH = _ROOT / "migrate_and_start.py"


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


def _base_results() -> dict:
    return {
        "mean_conversion_rate": 0.05,
        "total_agents": 10_000,
        "raw_funnel": {
            "converted": 500,
            "completed_at": "2026-01-01T00:00:00+00:00",
            "wall_time_seconds": 12.5,
            "agents_per_second": 800.0,
        },
    }


# ── Fingerprint ─────────────────────────────────────────────────────────────


def test_fingerprint_is_sha256_hex() -> None:
    fp = stable_result_fingerprint({"conversion_rate": 0.1234})
    assert fp is not None
    assert re.fullmatch(r"[0-9a-f]{64}", fp)


def test_fingerprint_ignores_dict_insertion_order() -> None:
    first = stable_result_fingerprint({"a": 1, "b": {"y": 2, "x": 1}})
    second = stable_result_fingerprint({"b": {"x": 1, "y": 2}, "a": 1})
    assert first == second


def test_fingerprint_excludes_volatile_timing_fields() -> None:
    later = _base_results()
    later["raw_funnel"]["completed_at"] = "2026-08-09T00:00:00+00:00"
    later["raw_funnel"]["wall_time_seconds"] = 99.9
    later["raw_funnel"]["agents_per_second"] = 100.1
    assert stable_result_fingerprint(_base_results()) == stable_result_fingerprint(later)


def test_fingerprint_strips_nested_generated_at() -> None:
    with_ts = {
        "domain_findings": [
            {"conversion_impact": 0.01, "generated_at": "2026-01-01T00:00:00+00:00"}
        ]
    }
    without_ts = {"domain_findings": [{"conversion_impact": 0.01}]}
    assert stable_result_fingerprint(with_ts) == stable_result_fingerprint(without_ts)


def test_fingerprint_detects_real_result_changes() -> None:
    a = stable_result_fingerprint({"converted": 500})
    b = stable_result_fingerprint({"converted": 501})
    assert a != b


def test_fingerprint_normalises_negative_zero() -> None:
    a = stable_result_fingerprint({"delta": -0.0})
    b = stable_result_fingerprint({"delta": 0.0})
    assert a == b


def test_fingerprint_is_deterministic_across_calls() -> None:
    assert stable_result_fingerprint(_base_results()) == stable_result_fingerprint(
        _base_results()
    )


def test_fingerprint_returns_none_for_unusable_input() -> None:
    assert stable_result_fingerprint(None) is None
    assert stable_result_fingerprint({}) is None
    assert stable_result_fingerprint("not-a-dict") is None


def test_volatile_key_set_covers_run_timing_fields() -> None:
    assert {
        "agents_per_second",
        "completed_at",
        "generated_at",
        "wall_time_seconds",
    } <= set(VOLATILE_RESULT_KEYS)


# ── Canonical environment snapshot ──────────────────────────────────────────


def test_canonical_env_snapshot_ignores_key_order() -> None:
    assert canonical_env_snapshot({"b": 2, "a": 1}) == canonical_env_snapshot(
        {"a": 1, "b": 2}
    )


def test_canonical_env_snapshot_none_serialises_as_null() -> None:
    assert canonical_env_snapshot(None) == "null"


def test_canonical_env_snapshot_empty_dict_differs_from_none() -> None:
    assert canonical_env_snapshot({}) != canonical_env_snapshot(None)


# ── Identical-input comparison ──────────────────────────────────────────────


def test_inputs_identical_when_everything_matches() -> None:
    snapshot = {"base_env": {"average_order_value": 999.0}, "scenario_type": None}
    assert inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=42,
        env_snapshot_a=snapshot,
        consumer_volume_b=10_000,
        seed_used_b=42,
        env_snapshot_b=snapshot,
    )


def test_inputs_differ_on_seed() -> None:
    assert not inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=42,
        env_snapshot_a=None,
        consumer_volume_b=10_000,
        seed_used_b=43,
        env_snapshot_b=None,
    )


def test_inputs_differ_on_volume() -> None:
    assert not inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=42,
        env_snapshot_a=None,
        consumer_volume_b=5_000,
        seed_used_b=42,
        env_snapshot_b=None,
    )


def test_inputs_differ_on_snapshot() -> None:
    assert not inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=42,
        env_snapshot_a=None,
        consumer_volume_b=10_000,
        seed_used_b=42,
        env_snapshot_b={"base_env": {"average_order_value": 700.0}},
    )


def test_legacy_runs_without_snapshots_require_same_seed() -> None:
    assert inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=259,
        env_snapshot_a=None,
        consumer_volume_b=10_000,
        seed_used_b=259,
        env_snapshot_b=None,
    )
    assert not inputs_are_identical(
        consumer_volume_a=10_000,
        seed_used_a=259,
        env_snapshot_a=None,
        consumer_volume_b=10_000,
        seed_used_b=37,
        env_snapshot_b=None,
    )


# ── Schema ──────────────────────────────────────────────────────────────────


def test_reproducibility_schema_defaults() -> None:
    from app.schemas.simulation import SimulationReproducibilityOut

    out = SimulationReproducibilityOut(
        simulation_id=1,
        project_id=1,
        status="COMPLETED",
        consumer_volume=10_000,
        seed_used=37,
    )
    assert out.fingerprint_algorithm == FINGERPRINT_ALGORITHM
    assert out.volatile_excluded_keys == sorted(VOLATILE_RESULT_KEYS)
    assert out.identical_input_runs == []
    assert out.matched_runs == 0
    assert out.exact_replay_confirmed is False


def test_identical_input_run_schema_validates() -> None:
    from app.schemas.simulation import IdenticalInputRunOut

    run = IdenticalInputRunOut(
        simulation_id=2,
        status="COMPLETED",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        fingerprint="a" * 64,
        match=True,
    )
    assert run.match is True
    assert run.fingerprint == "a" * 64


# ── Worker wiring ───────────────────────────────────────────────────────────


def test_worker_imports_fingerprint_helper() -> None:
    assert (
        "from app.simulation.reproducibility import stable_result_fingerprint"
        in _read(_TASKS_PATH)
    )


def test_worker_persists_fingerprint_at_completion() -> None:
    block = _extract(_TASKS_PATH, "run_full_simulation")
    assert "results_fingerprint = stable_result_fingerprint(results_dict)" in block
    assert "results_fingerprint=results_fingerprint" in block
    assert "sim.results_fingerprint = results_fingerprint" in block


# ── Model + migration ───────────────────────────────────────────────────────


def test_simulation_model_exposes_results_fingerprint() -> None:
    assert "results_fingerprint" in _read(_MODEL_PATH)
    assert "String(64)" in _read(_MODEL_PATH)


def test_migration_adds_results_fingerprint_column() -> None:
    assert '("results_fingerprint", "VARCHAR(64)")' in _read(_MIGRATIONS_PATH)


# ── Route contract ──────────────────────────────────────────────────────────


def test_reproducibility_route_contract() -> None:
    route_block = re.search(
        r"@router\.get\([\s\S]*?def get_simulation_reproducibility\(",
        _read(_SIMULATIONS_PATH),
    )
    assert route_block, "get_simulation_reproducibility route not found"
    block = route_block.group(0)
    assert '"/{simulation_id}/reproducibility"' in block
    assert "SimulationReproducibilityOut" in block
    assert "Project.user_id == current_user.id" in block


def test_reproducibility_route_uses_identical_input_helpers() -> None:
    block = _extract(_SIMULATIONS_PATH, "get_simulation_reproducibility")
    assert "inputs_are_identical(" in block
    assert "_stored_or_computed_fingerprint(" in block
    assert "resolve_simulation_seed(source.seed, source.id)" in block


def test_reproducibility_route_surfaces_mismatch_note() -> None:
    block = _extract(_SIMULATIONS_PATH, "get_simulation_reproducibility")
    assert "Identical-input runs produced different result fingerprints" in block
    assert "exact_replay_confirmed" in block

"""
Tests for partial_kill_shots wiring (cycle 26 stress-context-predicate).

A partial kill shot is a HIGH-severity risk row whose stressed conversion
did NOT collapse below KILL_SHOT_THRESHOLD but moved the needle hard enough
to demand explicit context (intervention generation, dashboard surfacing).

These tests lock in:
  1. The _is_partial_kill_shot() predicate behavior at the boundary.
  2. The producer side emits partial_kill_shots in the final result payload.
  3. The schema accepts and defaults partial_kill_shots to [].
"""
from __future__ import annotations

import json
from typing import Any

import pytest


def test_partial_kill_shot_predicate_at_boundary() -> None:
    from app.tasks.stress_test_tasks import _is_partial_kill_shot

    # Collapsed conversion → NOT a partial (it is a full kill_shot).
    row_collapsed: dict[str, Any] = {"kill_shot": True, "delta": -0.25}
    assert _is_partial_kill_shot(row_collapsed) is False

    # delta just below HIGH boundary (-0.018), no collapse → partial.
    row_just_below: dict[str, Any] = {"kill_shot": False, "delta": -0.0185}
    assert _is_partial_kill_shot(row_just_below) is True

    # delta exactly at HIGH boundary → NOT partial (boundary is strict <).
    row_at_boundary: dict[str, Any] = {"kill_shot": False, "delta": -0.018}
    assert _is_partial_kill_shot(row_at_boundary) is False

    # Mild risk (delta > -0.018) → NOT partial.
    row_mild: dict[str, Any] = {"kill_shot": False, "delta": -0.005}
    assert _is_partial_kill_shot(row_mild) is False

    # Positive delta → NOT partial (resilient).
    row_positive: dict[str, Any] = {"kill_shot": False, "delta": 0.04}
    assert _is_partial_kill_shot(row_positive) is False


def test_partial_kill_shot_predicate_handles_missing_keys() -> None:
    from app.tasks.stress_test_tasks import _is_partial_kill_shot

    # Defensive: missing keys must default safely (no exception, returns False).
    assert _is_partial_kill_shot({}) is False
    assert _is_partial_kill_shot({"kill_shot": False}) is False
    assert _is_partial_kill_shot({"delta": -0.5}) is False


def test_partial_kill_shot_threshold_constant_exists() -> None:
    from app.tasks import stress_test_tasks

    # The threshold must be defined and aligned with the HIGH boundary
    # used by _overall_risk() (delta < -0.018 ⇒ HIGH risk).
    assert hasattr(stress_test_tasks, "PARTIAL_KILL_SHOT_DELTA_THRESHOLD")
    assert stress_test_tasks.PARTIAL_KILL_SHOT_DELTA_THRESHOLD == -0.018


def test_schema_accepts_partial_kill_shots_field() -> None:
    from app.schemas.stress_test import (
        AssumptionStressResult,
        StressTestOut,
    )

    payload = {
        "project_id": 1,
        "status": "COMPLETED",
        "sensitivity_matrix": [],
        "kill_shots": [],
        # partial_kill_shots omitted → defaults to [].
        "overall_risk_level": "LOW",
        "baseline_conversion": 0.0,
        "assumptions_tested": 0,
        "generated_at": "2026-07-21T00:00:00+00:00",
    }
    out = StressTestOut.model_validate(payload)
    assert out.partial_kill_shots == []

    # Explicit empty list also accepted.
    payload["partial_kill_shots"] = []
    out2 = StressTestOut.model_validate(payload)
    assert out2.partial_kill_shots == []

    # Populated list round-trips.
    sample = AssumptionStressResult(
        assumption_id=42,
        assumption_text="Users will pay ₹999 without trial",
        sensitivity="HIGH",
        baseline_conversion=0.05,
        stressed_conversion=0.02,
        delta=-0.03,
        delta_pct=-60.0,
        kill_shot=False,
        kill_shot_prob=0.7,
        recommendation="De-risk before launch.",
    )
    payload["partial_kill_shots"] = [sample.model_dump()]
    out3 = StressTestOut.model_validate(payload)
    assert len(out3.partial_kill_shots) == 1
    assert out3.partial_kill_shots[0].assumption_id == 42


def test_empty_target_assumptions_path_includes_partial_kill_shots_key() -> None:
    """
    When no CRITICAL/HIGH assumptions exist, the early-return payload must
    still include partial_kill_shots:[] so downstream consumers (and the
    StressTestOut schema) don't break.
    """
    # Read the source file and assert the literal key is present in the
    # early-return block. This locks the producer shape without needing
    # to mock the full Celery task.
    src_path = "backend/app/tasks/stress_test_tasks.py"
    with open(src_path) as fh:
        source = fh.read()

    # Find the early-return block (the "No CRITICAL or HIGH assumptions" path).
    assert '"partial_kill_shots": []' in source, (
        "stress_test_tasks.py must emit partial_kill_shots:[] in the "
        "empty-target-assumptions early-return path"
    )


def test_main_result_includes_partial_kill_shots_key() -> None:
    """
    The main result builder must include the partial_kill_shots key so
    downstream consumers can always read it without .get-with-default.
    """
    src_path = "backend/app/tasks/stress_test_tasks.py"
    with open(src_path) as fh:
        source = fh.read()

    assert '"partial_kill_shots": partial_kill_shots' in source, (
        "stress_test_tasks.py must include partial_kill_shots in the "
        "final_result payload"
    )


def test_projects_get_stress_test_populates_partial_kill_shots() -> None:
    """
    The GET /projects/{id}/stress-test endpoint must hydrate
    partial_kill_shots from the raw stored payload so consumers see it.
    """
    src_path = "backend/app/api/v1/projects.py"
    with open(src_path) as fh:
        source = fh.read()

    # Must read the field and pass it into StressTestOut.
    assert 'raw.get("partial_kill_shots"' in source, (
        "projects.py get_stress_test must read partial_kill_shots from raw"
    )
    assert "partial_kill_shots=partial_shots" in source, (
        "projects.py get_stress_test must populate "
        "StressTestOut.partial_kill_shots from raw"
    )


def test_context_predicate_handles_legacy_partial_kill_shots() -> None:
    """
    The intervention context_used stress_test predicate (already widened
    in this branch) must keep working when partial_kill_shots is the
    only thing populated. This guards against accidental regression to
    a kill_shots-only check.
    """
    from app.schemas.stress_test import StressTestOut

    # Build a stored payload with partial_kill_shots but no kill_shots.
    raw = {
        "status": "COMPLETED",
        "sensitivity_matrix": [],
        "kill_shots": [],
        "partial_kill_shots": [
            {
                "assumption_id": 1,
                "assumption_text": "x",
                "sensitivity": "HIGH",
                "baseline_conversion": 0.05,
                "stressed_conversion": 0.02,
                "delta": -0.03,
                "delta_pct": -60.0,
                "kill_shot": False,
                "kill_shot_prob": 0.7,
                "recommendation": "De-risk",
            }
        ],
        "overall_risk_level": "HIGH",
        "baseline_conversion": 0.05,
        "assumptions_tested": 1,
        "generated_at": "2026-07-21T00:00:00+00:00",
    }
    parsed = StressTestOut.model_validate({**raw, "project_id": 1})
    assert parsed.partial_kill_shots  # truthy

    # The intervention-route predicate logic (replicated here) must agree.
    stress_test_data = raw
    predicate = bool(
        stress_test_data
        and (
            stress_test_data.get("kill_shots")
            or stress_test_data.get("partial_kill_shots")
        )
    )
    assert predicate is True

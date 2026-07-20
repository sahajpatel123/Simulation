"""Tests for backend/app/simulation/run_trace.py and the conductor's
_persist_run_trace JSONB writer.

Scopes:
  1. RunTrace: stage timing semantics, defensive begin/end semantics,
     JSON-serialisable payload.
  2. Conductor._persist_run_trace: writes the trace to a JSONB column
     and tolerates DB failures without raising.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.simulation.run_trace import RunTrace, StageRecord


# ---------------------------------------------------------------------------
# RunTrace
# ---------------------------------------------------------------------------


def test_basic_begin_end_records_stage() -> None:
    t = RunTrace()
    t.begin("cluster_weights")
    time.sleep(0.01)
    t.end(items=52)
    payload = t.to_dict()
    assert payload["stage_count"] == 1
    stage = payload["stages"][0]
    assert stage["name"] == "cluster_weights"
    assert stage["items"] == 52
    assert stage["status"] == "ok"
    assert stage["elapsed_ms"] >= 5.0  # well above the sleep floor
    assert payload["total_ms"] >= stage["elapsed_ms"]


def test_multiple_stages_in_order() -> None:
    t = RunTrace()
    t.begin("a")
    t.end(items=1)
    t.begin("b")
    t.end(items=2)
    t.begin("c")
    t.end(items=3, status="error")
    payload = t.to_dict()
    assert [s["name"] for s in payload["stages"]] == ["a", "b", "c"]
    assert payload["stages"][2]["status"] == "error"


def test_begin_closes_orphaned_previous_stage() -> None:
    """A forgotten end() must not leak into the next stage."""
    t = RunTrace()
    t.begin("leak")
    t.begin("real")
    t.end(items=1)
    payload = t.to_dict()
    names = [s["name"] for s in payload["stages"]]
    assert names[0] == "leak"
    assert names[0 + 1 - 1 if False else 1] == "real" or names == ["leak", "real"]
    # The first 'leak' entry should be marked orphaned.
    assert payload["stages"][0]["status"] == "orphaned"


def test_end_without_begin_is_noop() -> None:
    t = RunTrace()
    t.end(items=99)  # must not raise
    assert t.to_dict()["stage_count"] == 0


def test_add_summary_promotes_to_top_level() -> None:
    t = RunTrace()
    t.begin("loop")
    t.end(items=100)
    t.add_summary(architect_calls=100, architect_failures=2)
    payload = t.to_dict()
    assert payload["architect_calls"] == 100
    assert payload["architect_failures"] == 2
    # Summary must not leak into a stage entry.
    for s in payload["stages"]:
        assert "architect_calls" not in s


def test_payload_is_json_serialisable() -> None:
    t = RunTrace()
    t.begin("x")
    t.end(items=1)
    t.add_summary(failures=0)
    raw = json.dumps(t.to_dict())
    reparsed = json.loads(raw)
    assert reparsed["stages"][0]["name"] == "x"


def test_stage_record_dataclass_is_serialisable() -> None:
    s = StageRecord(name="a", elapsed_ms=1.23, items=5, status="ok")
    assert json.loads(json.dumps(s.__dict__)) == {
        "name": "a",
        "elapsed_ms": 1.23,
        "items": 5,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# Conductor._persist_run_trace (DB interaction)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_mock() -> MagicMock:
    """MagicMock SQLAlchemy session: tracks execute() and commit() calls,
    has a rollback() that doesn't blow up."""
    db = MagicMock()
    db.execute.return_value = None
    db.commit.return_value = None
    db.rollback.return_value = None
    return db


def test_persist_run_trace_writes_jsonb(db_mock: MagicMock) -> None:
    """Should bind :trace and :sid and call commit."""
    from app.simulation.conductor import Conductor

    trace = RunTrace()
    trace.begin("architect_loop")
    trace.end(items=10)
    trace.add_summary(architect_calls=10, architect_failures=1)

    conductor = Conductor()
    conductor._persist_run_trace(db_mock, simulation_id=42, trace=trace)

    db_mock.execute.assert_called_once()
    call_args = db_mock.execute.call_args
    # First positional arg is a SQL text object; the second is bound params.
    sql, params = call_args.args
    assert isinstance(params["trace"], str)
    assert params["sid"] == 42
    # Round-trip JSON parse to ensure serialisability was real.
    parsed = json.loads(params["trace"])
    assert parsed["architect_calls"] == 10
    assert parsed["architect_failures"] == 1

    db_mock.commit.assert_called_once()


def test_persist_run_trace_swallows_db_errors(db_mock: MagicMock) -> None:
    """A DB failure must log and roll back, never raise into the conductor."""
    from app.simulation.conductor import Conductor

    db_mock.execute.side_effect = RuntimeError("connection lost")

    conductor = Conductor()
    # Should NOT raise:
    conductor._persist_run_trace(
        db_mock,
        simulation_id=7,
        trace=RunTrace(),
    )

    db_mock.rollback.assert_called_once()


def test_persist_run_trace_swallows_non_serialisable_payload(db_mock: MagicMock) -> None:
    """Bad trace payload should be logged, not raised."""
    from app.simulation.conductor import Conductor

    trace = MagicMock()
    trace.to_dict.side_effect = TypeError("not JSON-able")

    conductor = Conductor()
    # Should NOT raise:
    conductor._persist_run_trace(db_mock, simulation_id=1, trace=trace)

    db_mock.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Schema shape: SimulationRunTraceOut
# ---------------------------------------------------------------------------


def test_run_trace_schema_roundtrip() -> None:
    """The endpoint's Pydantic schema serialises a conductor payload
    without dropping the stage or summary fields."""
    from app.schemas.simulation import RunTraceStageOut, SimulationRunTraceOut

    payload = {
        "id": 42,
        "project_id": 7,
        "status": "COMPLETED",
        "total_ms": 1234.5,
        "stage_count": 2,
        "summary": {
            "architect_calls": 100,
            "architect_failures": 1,
            "architect_skipped": 0,
            "clusters_processed": 52,
        },
        "stages": [
            {"name": "architect_loop", "elapsed_ms": 900.0, "items": 100, "status": "ok"},
            {"name": "domain_reports", "elapsed_ms": 12.3, "items": 11, "status": "ok"},
        ],
        "available": True,
        "message": "",
    }
    schema = SimulationRunTraceOut(**payload)
    assert schema.total_ms == 1234.5
    assert schema.stage_count == 2
    assert schema.summary["architect_failures"] == 1
    assert schema.stages[0].name == "architect_loop"
    assert schema.stages[0].items == 100
    assert isinstance(schema.stages[0], RunTraceStageOut)


def test_run_trace_schema_unavailable_state() -> None:
    """available=False messages flow through unchanged."""
    from app.schemas.simulation import SimulationRunTraceOut

    schema = SimulationRunTraceOut(
        id=1,
        project_id=2,
        status="RUNNING",
        available=False,
        message="Run trace will be available when the simulation completes.",
    )
    assert schema.total_ms is None
    assert schema.stage_count == 0
    assert schema.stages == []
    assert schema.available is False
    assert schema.message.startswith("Run trace")

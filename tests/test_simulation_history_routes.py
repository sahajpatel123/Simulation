"""Route-level tests for the lightweight simulation-history/trend reads."""
from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import patch

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _rows() -> list[dict]:
    return [
        {
            "id": 1,
            "status": "COMPLETED",
            "signal_quality": 0.6,
            "created_at": datetime(2026, 8, 1, 12, 0),
            "conversion_rate": 0.04,
        },
        {
            "id": 2,
            "status": "COMPLETED",
            "signal_quality": None,
            "created_at": datetime(2026, 8, 2, 12, 0),
            "conversion_rate": 0.06,
        },
    ]


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def all(self) -> list[dict]:
        return list(self.rows)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self.rows)


class _FakeSession:
    def __init__(
        self,
        rows: list[dict] | None = None,
        sql_calls: list[str] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else _rows()
        self.sql_calls = sql_calls

    def execute(self, *args, **kwargs) -> _FakeResult:
        if self.sql_calls is not None and args:
            statement = args[0]
            self.sql_calls.append(getattr(statement, "text", str(statement)))
        return _FakeResult(self.rows)


def _user() -> object:
    return type("U", (), {"id": 42})()


def _call_history(
    *,
    rows: list[dict] | None = None,
    sql_calls: list[str] | None = None,
) -> dict:
    from app.api.v1 import projects as projects_mod

    db = _FakeSession(rows=rows, sql_calls=sql_calls)
    with patch.object(
        projects_mod, "get_owned_project", return_value=object()
    ):
        return projects_mod.get_simulation_history(
            project_id=10,
            db=db,
            current_user=_user(),
        )


def _call_trend(
    *,
    rows: list[dict] | None = None,
    sql_calls: list[str] | None = None,
):
    from app.api.v1 import projects as projects_mod

    db = _FakeSession(rows=rows, sql_calls=sql_calls)
    with patch.object(
        projects_mod, "get_owned_project", return_value=object()
    ):
        return projects_mod.get_simulation_trend(
            project_id=10,
            db=db,
            current_user=_user(),
        )


def test_history_uses_projected_sql_not_full_results_payload() -> None:
    calls: list[str] = []
    _call_history(sql_calls=calls)

    sql = "\n".join(calls)
    assert "results_json->>'population_weighted_conversion'" in sql
    assert "results_json->>'conversion_rate'" in sql
    assert "ORDER BY s.created_at ASC" in sql
    # The full JSONB column must never be selected as a bare column.
    assert "results_json," not in sql
    assert "results_json FROM" not in sql


def test_history_builds_payload_from_projected_rows() -> None:
    out = _call_history()

    assert out["project_id"] == 10
    assert out["total_runs"] == 2
    assert out["best_run_id"] == 2
    history = out["history"]
    assert history[0]["conversion_rate"] == 0.04
    assert history[0]["delta_from_prev"] is None
    assert history[1]["conversion_rate"] == 0.06
    assert history[1]["delta_from_prev"] == 0.02
    assert history[1]["direction"] == "UP"


def test_history_handles_empty_projection() -> None:
    out = _call_history(rows=[])

    assert out["total_runs"] == 0
    assert out["history"] == []
    assert out["best_run_id"] is None


def test_trend_uses_projected_sql_not_full_results_payload() -> None:
    calls: list[str] = []
    _call_trend(sql_calls=calls)

    sql = "\n".join(calls)
    assert "results_json->>'population_weighted_conversion'" in sql
    assert "results_json->>'conversion_rate'" in sql
    assert "results_json," not in sql
    assert "results_json FROM" not in sql


def test_trend_builds_rollup_from_projected_rows() -> None:
    out = _call_trend()

    assert out.project_id == 10
    assert out.total_runs == 2
    assert out.completed_runs == 2
    assert out.best_run.simulation_id == 2
    assert out.worst_run.simulation_id == 1
    assert out.latest_run.simulation_id == 2
    assert out.conversion_stats["mean"] == 0.05
    assert [h.conversion_rate for h in out.history] == [0.04, 0.06]


def test_trend_handles_empty_projection() -> None:
    out = _call_trend(rows=[])

    assert out.total_runs == 0
    assert out.completed_runs == 0
    assert out.best_run is None
    assert out.worst_run is None
    assert out.latest_run is None

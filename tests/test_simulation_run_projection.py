"""Tests for the shared projected simulation-run SQL read."""
from __future__ import annotations

from datetime import datetime


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
        *,
        statement: list[str] | None = None,
        params: list[dict] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.statement = statement
        self.params = params

    def execute(self, statement, params) -> _FakeResult:
        if self.statement is not None:
            self.statement.append(getattr(statement, "text", str(statement)))
        if self.params is not None:
            self.params.append(params)
        return _FakeResult(self.rows)


def test_fetch_projected_run_rows_binds_project_id_and_returns_dicts() -> None:
    from app.simulation.simulation_run_projection import (
        fetch_projected_run_rows,
    )

    statement: list[str] = []
    params: list[dict] = []
    session = _FakeSession(
        [
            {
                "id": 1,
                "status": "COMPLETED",
                "signal_quality": 0.5,
                "created_at": datetime(2026, 8, 1, 12, 0),
                "conversion_rate": "0.04",
            }
        ],
        statement=statement,
        params=params,
    )

    rows = fetch_projected_run_rows(session, project_id=42)

    assert rows == [
        {
            "id": 1,
            "status": "COMPLETED",
            "signal_quality": 0.5,
            "created_at": datetime(2026, 8, 1, 12, 0),
            "conversion_rate": "0.04",
        }
    ]
    assert params == [{"pid": 42}]
    assert len(statement) == 1


def test_projection_sql_is_defensive_and_projected_only() -> None:
    from app.simulation.simulation_run_projection import (
        SIMULATION_RUN_PROJECTION_SQL,
    )

    sql = getattr(SIMULATION_RUN_PROJECTION_SQL, "text", str(SIMULATION_RUN_PROJECTION_SQL))
    assert "results_json->>'population_weighted_conversion'" in sql
    assert "results_json->>'conversion_rate'" in sql
    assert "jsonb_typeof(s.results_json) = 'object'" in sql
    assert "IN ('number', 'string')" in sql
    assert "ORDER BY s.created_at ASC, s.id ASC" in sql
    # Never pull the full payload across the wire.
    assert "results_json," not in sql
    assert "results_json FROM" not in sql
    # Parsing bad values happens in Python, not with an SQL cast that can
    # abort the query for the whole project.
    assert "::float" not in sql

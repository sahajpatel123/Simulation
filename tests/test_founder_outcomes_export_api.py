"""Route-level tests for the /analytics/founder-outcomes/export endpoint."""
from __future__ import annotations

import asyncio
import re
import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


def _rows() -> list[dict]:
    return [
        {
            "id": 1,
            "simulation_id": 7,
            "project_id": 10,
            "project_title": "Lean tool",
            "created_at": "2026-08-07T20:00:00+00:00",
            "launched": True,
            "actual_conversion_rate": 0.05,
            "signal_quality_at_run": 0.62,
            "days_since_launch": 30,
            "data_confidence": "ESTIMATED",
            "product_changed_since_sim": False,
            "pricing_changed": True,
            "target_market_changed": False,
            "validated": True,
            "learning_weight": 0.8,
            "notes": "launched in beta",
            "results_json": {"population_weighted_conversion": 0.04},
        }
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


def _call_route(
    *,
    format: str = "csv",
    session: _FakeSession | None = None,
    is_admin: bool = True,
):
    from app.api.v1 import analytics as analytics_mod

    db = session if session is not None else _FakeSession()
    current_user = type(
        "U",
        (),
        {"id": 42, "is_admin": is_admin, "email": "admin@example.com"},
    )()
    return analytics_mod.export_founder_outcomes(
        format=format,
        db=db,
        current_user=current_user,
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_founder_outcomes_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="founder-outcomes.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "id,simulation_id,project_id,project_title,created_at,launched" in body
    assert (
        "1,7,10,Lean tool,2026-08-07T20:00:00+00:00,true,0.05,0.04,25.0,"
        "0.62,30,ESTIMATED,false,true,false,true,0.8,launched in beta"
    ) in body


def test_export_founder_outcomes_json() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"total": 1' in body
    assert '"predicted_conversion_rate": 0.04' in body
    assert '"project_title": "Lean tool"' in body


def test_export_founder_outcomes_empty_rows() -> None:
    session = _FakeSession(rows=[])
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "id,simulation_id,project_id,project_title" in body
    assert "1,7,10" not in body


def test_export_founder_outcomes_left_joins_simulation_and_project() -> None:
    """Deleted simulation/project rows must not silently drop audit rows."""
    calls: list[str] = []
    session = _FakeSession(rows=_rows(), sql_calls=calls)
    _body(_call_route(session=session))

    sql = "\n".join(calls)
    assert "LEFT JOIN simulations s ON s.id = fo.simulation_id" in sql
    assert "LEFT JOIN projects p ON p.id = fo.project_id" in sql
    # A plain inner join would lose rows when either FK target has been deleted.
    assert len(re.findall(r"LEFT JOIN simulations", sql)) == 1
    assert len(re.findall(r"LEFT JOIN projects", sql)) == 1
    assert not re.search(r"(?m)^\s*JOIN ", sql)


def test_export_founder_outcomes_requires_admin() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_route(is_admin=False)
    assert exc.value.status_code == 403

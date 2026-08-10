"""Route-level tests for the failure-attribution endpoints."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub

from app.schemas.failure_attribution import FailureAttributionOut  # noqa: E402

_MISSING = object()


def _row(**overrides) -> dict:
    row = {
        "id": 1,
        "simulation_id": 7,
        "project_id": 10,
        "days_since_launch": 30,
        "actual_conversion_rate": 0.03,
        "primary_failure_reason": "PRICING",
        "product_changed_since_sim": False,
        "pricing_changed": True,
        "target_market_changed": False,
        "data_confidence": "ESTIMATED",
        "signal_quality_at_run": 0.6,
        "learning_weight": 0.36,
        "results_json": {"population_weighted_conversion": 0.04},
    }
    row.update(overrides)
    return row


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


class _FakeProject:
    def __init__(self) -> None:
        self.id = 10
        self.user_id = 42


class _FakeProjectQuery:
    def __init__(self, project) -> None:
        self.project = project

    def filter(self, *args, **kwargs) -> _FakeProjectQuery:
        return self

    def first(self):
        return self.project


class _FakeSession:
    def __init__(
        self,
        *,
        rows: list[dict] | None = None,
        project=_MISSING,
        sql_calls: list[str] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.project = _FakeProject() if project is _MISSING else project
        self.sql_calls = sql_calls

    def query(self, *args, **kwargs) -> _FakeProjectQuery:
        return _FakeProjectQuery(self.project)

    def execute(self, statement, params=None) -> _FakeResult:
        if self.sql_calls is not None:
            self.sql_calls.append(str(statement))
        return _FakeResult(self.rows)


def _user() -> object:
    return type("U", (), {"id": 42})()


def _call_get(
    *,
    project_id: int = 10,
    db=None,
    current_user=None,
) -> FailureAttributionOut:
    from app.api.v1 import outcomes as out_mod

    return out_mod.get_failure_attribution(
        project_id=project_id,
        db=db if db is not None else _FakeSession(),
        current_user=current_user or _user(),
    )


async def _body_bytes(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def test_returns_failure_attribution_payload() -> None:
    result = _call_get(
        db=_FakeSession(rows=[
            _row(primary_failure_reason="PRICING", actual_conversion_rate=0.01),
            _row(primary_failure_reason="PRICING", actual_conversion_rate=0.02),
            _row(primary_failure_reason="ONBOARDING", actual_conversion_rate=0.05),
        ])
    )

    assert isinstance(result, FailureAttributionOut)
    assert result.project_id == 10
    assert result.total_outcomes == 3
    assert result.attributed_count == 3
    assert result.top_reason == "PRICING"
    assert result.reasons[0].count == 2
    assert result.reasons[1].count == 1


def test_requires_project_owner() -> None:
    with pytest.raises(HTTPException) as exc:
        _call_get(db=_FakeSession(project=None))
    assert exc.value.status_code == 404
    assert "Project not found" in exc.value.detail


def test_query_is_scoped_to_project_and_joins_simulation() -> None:
    calls: list[str] = []
    _call_get(db=_FakeSession(rows=[_row()], sql_calls=calls))

    sql = "\n".join(calls)
    assert "FROM founder_outcomes fo" in sql
    assert "LEFT JOIN simulations s ON s.id = fo.simulation_id" in sql
    assert "fo.project_id = :pid" in sql
    assert ":pid" in sql and "fo.project_id" in sql


def test_export_returns_csv_attachment() -> None:
    from app.api.v1 import outcomes as out_mod

    response = out_mod.export_failure_attribution(
        project_id=10,
        format="csv",
        db=_FakeSession(rows=[_row()]),
        current_user=_user(),
    )
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "failure-attribution.csv" in response.headers["Content-Disposition"]
    assert "section,Summary" in body
    assert "section,Reasons" in body
    assert "PRICING" in body


def test_export_returns_json_attachment() -> None:
    import json

    from app.api.v1 import outcomes as out_mod

    response = out_mod.export_failure_attribution(
        project_id=10,
        format="json",
        db=_FakeSession(rows=[_row()]),
        current_user=_user(),
    )
    body = asyncio.run(_body_bytes(response)).decode()

    assert response.headers["Content-Type"].startswith("application/json")
    parsed = json.loads(body)
    assert parsed["metadata"]["project_id"] == 10
    assert parsed["failure_attribution"]["top_reason"] == "PRICING"


def test_export_rejects_unsupported_format() -> None:
    from app.api.v1 import outcomes as out_mod

    with pytest.raises(HTTPException) as exc:
        out_mod.export_failure_attribution(
            project_id=10,
            format="xlsx",
            db=_FakeSession(),
            current_user=_user(),
        )
    assert exc.value.status_code == 400
    assert "unsupported export format" in exc.value.detail


def test_failure_attribution_routes_registered_as_get() -> None:
    from app.api.v1 import outcomes as out_mod

    expected = {
        "/projects/{project_id}/failure-attribution",
        "/projects/{project_id}/failure-attribution/export",
    }
    paths = {r.path for r in out_mod.router.routes}
    assert expected <= paths

    for route in out_mod.router.routes:
        if route.path in expected:
            assert "GET" in (route.methods or set())

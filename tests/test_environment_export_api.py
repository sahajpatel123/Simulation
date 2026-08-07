"""Route-level tests for the /projects/{id}/environment/export endpoint."""
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


class _Project:
    def __init__(self) -> None:
        self.id = 10


class _Environment:
    def __init__(self) -> None:
        self.id = 1
        self.project_id = 10
        self.mode = "MANUAL"
        self.consumer_volume = 10000
        self.growth_rate_per_month = 5.0
        self.average_order_value = 999.0
        self.price_sensitivity = 0.5
        self.market_maturity = 0.3
        self.scenario_type = None
        self.manual_params_json = {"a": 1}
        self.trend_data_json = None


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.items[0] if self.items else None


class _FakeSession:
    def __init__(self, environment: object | bool | None = None) -> None:
        if environment is False:
            self.environment = None
        else:
            self.environment = environment if environment is not None else _Environment()

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name == "Project":
            return _FakeQuery([_Project()])
        if name == "Environment":
            return _FakeQuery([self.environment])
        return _FakeQuery([])


def _call_route(*, project_id: int = 10, session: _FakeSession | None = None):
    from app.api.v1 import projects as proj_mod

    db = session if session is not None else _FakeSession()
    return proj_mod.export_environment(
        project_id=project_id,
        db=db,
        current_user=type("U", (), {"id": 42})(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_environment_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'filename="environment-10.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "environment_id,project_id,mode,consumer_volume" in body
    assert "1,10,MANUAL,10000,5.0,999.0,0.5,0.3" in body
    assert "user_id,42" in body


def test_export_environment_empty_returns_header_only() -> None:
    session = _FakeSession(environment=False)
    resp = _call_route(session=session)

    body = _body(resp).decode("utf-8")
    assert "environment_id,project_id,mode,consumer_volume" in body
    assert "MANUAL" not in body


def test_export_environment_missing_project_raises_404() -> None:
    class NoProjectSession(_FakeSession):
        def query(self, model, *args, **kwargs):
            name = getattr(model, "__name__", "")
            if name == "Project":
                return _FakeQuery([])
            return _FakeQuery([self.environment])

    with pytest.raises(HTTPException) as exc:
        _call_route(session=NoProjectSession())
    assert exc.value.status_code == 404

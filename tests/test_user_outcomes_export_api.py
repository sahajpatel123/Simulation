"""Route-level tests for the /me/outcomes/export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _Outcome:
    def __init__(self) -> None:
        self.id = 1
        self.project_id = 10
        self.actual_conversion_rate = 0.042
        self.actual_mrr = 1000.0
        self.actual_cac = 50.0
        self.actual_churn_rate = 0.03
        self.created_at = "2026-08-08T07:00:00+00:00"


class _Project:
    def __init__(self) -> None:
        self.id = 10
        self.user_id = 42


class _FakeQuery:
    def __init__(self, items: list | None = None) -> None:
        self.items = items if items is not None else []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return list(self.items)


class _FakeSession:
    def __init__(self, rows: list | None = None) -> None:
        self.rows = rows if rows is not None else [(_Outcome(), _Project())]

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name in {"Outcome", "Project"}:
            return _FakeQuery(self.rows)
        return _FakeQuery([])


def _call_route(*, session: _FakeSession | None = None):
    from app.api.v1 import users as user_mod

    db = session if session is not None else _FakeSession()
    return user_mod.export_my_outcomes(
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


def test_export_my_outcomes_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'attachment; filename="my-outcomes.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "outcome_id,project_id,actual_conversion_rate" in body
    assert "1,10,0.042,1000.0,50.0,0.03" in body
    assert "user_id,42" in body

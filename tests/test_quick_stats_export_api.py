"""Route-level tests for the /me/quick-stats/export endpoint."""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timezone

if "razorpay" not in sys.modules:
    stub = types.ModuleType("razorpay")
    stub.Client = object  # type: ignore[attr-defined]
    sys.modules["razorpay"] = stub


class _FakeQuery:
    def __init__(self, count: int = 1) -> None:
        self.count_value = count

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self.count_value


class _FakeSession:
    def __init__(self) -> None:
        pass

    def query(self, model, *args, **kwargs):
        name = getattr(model, "__name__", "")
        if name in {"Project", "Simulation", "Decision", "Outcome"}:
            return _FakeQuery(count=1)
        return _FakeQuery(count=0)


class _User:
    def __init__(self) -> None:
        self.id = 42
        self.created_at = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _call_route(*, format: str = "csv", session: _FakeSession | None = None):
    from app.api.v1 import users as user_mod

    db = session if session is not None else _FakeSession()
    return user_mod.export_my_quick_stats(
        format=format,
        db=db,
        current_user=_User(),
    )


async def _collect(resp) -> bytes:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


def _body(resp) -> bytes:
    return asyncio.run(_collect(resp))


def test_export_my_quick_stats_returns_csv() -> None:
    resp = _call_route()

    assert resp.media_type == "text/csv; charset=utf-8"
    assert 'attachment; filename="my-quick-stats.csv"' in resp.headers["Content-Disposition"]
    body = _body(resp).decode("utf-8")
    assert "user_id,total_projects,total_simulations" in body
    assert "42,1,1,1,1" in body
    assert "user_id,42" in body


def test_export_my_quick_stats_format_json_returns_payload() -> None:
    resp = _call_route(format="json")

    assert resp.media_type == "application/json; charset=utf-8"
    body = _body(resp).decode("utf-8")
    assert '"quick_stats"' in body
    assert '"user_id": 42' in body
    assert '"total_projects": 1' in body

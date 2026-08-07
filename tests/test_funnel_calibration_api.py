"""Route-level tests for the funnel calibration digest endpoint."""
from __future__ import annotations

import sys
import types

import pytest

from app.schemas.funnel_calibration import FunnelCalibrationDigestOut


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


class _FakeProjectQuery:
    """Ownership lookup returns a valid project row."""

    def filter(self, *args, **kwargs) -> _FakeProjectQuery:
        return self

    def first(self):
        return type("P", (), {"id": 1, "user_id": 42})()


class _FakeSession:
    def __init__(
        self,
        rows: list[dict] | None = None,
        sql_calls: list[str] | None = None,
    ) -> None:
        self.rows = rows if rows is not None else []
        self.sql_calls = sql_calls

    def query(self, *args, **kwargs) -> _FakeProjectQuery:
        return _FakeProjectQuery()

    def execute(self, *args, **kwargs) -> _FakeResult:
        statement = args[0] if args else kwargs.get("statement")
        if self.sql_calls is not None:
            self.sql_calls.append(
                getattr(statement, "text", str(statement))
            )
        return _FakeResult(self.rows)


def _call_route(session: _FakeSession) -> FunnelCalibrationDigestOut:
    from app.api.v1 import outcomes as out_mod

    return out_mod.get_funnel_calibration_digest(
        project_id=1,
        db=session,
        current_user=type("U", (), {"id": 42})(),
    )


def test_funnel_calibration_digest_filters_unvalidated_outcomes(
    monkeypatch,
) -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)

    calls: list[str] = []
    result = _call_route(_FakeSession(sql_calls=calls))
    assert result.outcome_count == 0

    sql = "\n".join(calls)
    assert "fo.validated = true" in sql
    assert "fo.learning_weight > 0" in sql
    assert "WHERE fo.project_id = :pid" in sql

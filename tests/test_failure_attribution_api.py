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


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch) -> None:
    """Keep route tests hermetic when a local Redis is reachable.

    The digest now caches through ``app.core.redis_client``; without this
    fixture, tests sharing user 42 / project 10 could hit a real Redis
    key written by an earlier test and never exercise the SQL path.
    """
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)


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


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        self.setex_calls.append((key, ttl_seconds, value))
        self.store[key] = value

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                n += 1
        return n


def _patch_redis(monkeypatch, fake) -> None:
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)


def test_failure_attribution_caches_payload_and_skips_db(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)
    sql_calls: list[str] = []

    first = _call_get(
        db=_FakeSession(rows=[_row()], sql_calls=sql_calls),
    )
    second = _call_get(
        db=_FakeSession(rows=[_row()], sql_calls=sql_calls),
    )

    assert first.top_reason == "PRICING"
    assert second.top_reason == "PRICING"
    assert len(fake.setex_calls) == 1
    assert fake.setex_calls[0][1] == 120
    # One SQL scan on the miss; the cache hit must not touch the DB.
    assert len(sql_calls) == 1


def test_failure_attribution_cache_isolated_per_user(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_get(current_user=_user())
    _call_get(current_user=type("U", (), {"id": 99})())

    assert len(fake.setex_calls) == 2
    keys = {call[0] for call in fake.setex_calls}
    assert len(keys) == 2


def test_failure_attribution_cache_isolated_per_project(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_get(project_id=10)
    _call_get(project_id=11)

    assert len(fake.setex_calls) == 2
    keys = {call[0] for call in fake.setex_calls}
    assert len(keys) == 2


def test_failure_attribution_cache_noop_when_redis_down(monkeypatch) -> None:
    from app.core import redis_client

    monkeypatch.setattr(redis_client, "get_redis_client", lambda: None)

    first = _call_get(db=_FakeSession(rows=[_row()]))
    second = _call_get(db=_FakeSession(rows=[_row()]))

    assert first.top_reason == "PRICING"
    assert second.top_reason == "PRICING"


def test_failure_attribution_export_shares_digest_cache(monkeypatch) -> None:
    from app.api.v1 import outcomes as out_mod

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    first = out_mod.export_failure_attribution(
        project_id=10,
        format="csv",
        db=_FakeSession(rows=[_row()]),
        current_user=_user(),
    )
    first_body = asyncio.run(_body_bytes(first)).decode()
    second = out_mod.export_failure_attribution(
        project_id=10,
        format="csv",
        db=_FakeSession(rows=[_row()]),
        current_user=_user(),
    )
    second_body = asyncio.run(_body_bytes(second)).decode()

    assert "PRICING" in first_body
    # Metadata timestamps are regenerated per export; the digest section
    # must be byte-identical because the second export hits the cache.
    def digest_section(text: str) -> str:
        return text.split("section,Summary", 1)[1]

    assert digest_section(first_body) == digest_section(second_body)
    # One miss + one hit — no third write when the JSON route reuses it.
    assert len(fake.setex_calls) == 1
    json_payload = _call_get(
        db=_FakeSession(rows=[_row()]),
    )
    assert json_payload.top_reason == "PRICING"
    assert len(fake.setex_calls) == 1


def test_failure_attribution_namespace_consistency() -> None:
    """Pin the cache namespace constant and every use site."""
    import inspect

    from app.api.v1 import outcomes as out_mod

    namespace = out_mod._FAILURE_ATTRIBUTION_CACHE_NAMESPACE
    assert namespace == "project-failure-attribution"

    src = inspect.getsource(out_mod)
    # Read path (get + set) and the outcome-feedback invalidation site
    # must all use the constant, never a hardcoded literal.
    assert src.count("namespace=_FAILURE_ATTRIBUTION_CACHE_NAMESPACE") >= 3
    assert f'namespace="{namespace}"' not in src

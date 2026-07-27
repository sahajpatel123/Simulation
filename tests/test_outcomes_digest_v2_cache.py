"""Route-level tests for the /projects/{id}/outcomes-digest cache.

Mirrors the cache-isolation tests for the other
per-project tiles. Pins cache hit short-circuit, per-user
+ per-project key isolation, Redis-down no-op, and
namespace-string consistency between the read path and
all 3 invalidation sites.
"""
from __future__ import annotations

import pytest


def _patch_redis(monkeypatch, fake) -> None:
    from app.core import redis_client

    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: fake,
    )


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls: list[tuple[str, int, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(
        self, key: str, ttl_seconds: int, value: str,
    ) -> None:
        self.setex_calls.append((key, ttl_seconds, value))
        self.store[key] = value

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *_):
        return self

    def first(self):
        return None

    def scalar(self):
        return None

    def all(self):
        return []


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


def _call_route(current_user_id: int = 42, project_id: int = 1):
    from app.api.v1 import outcomes as out_mod

    return out_mod.get_outcomes_digest(
        project_id=project_id,
        db=_FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_outcomes_digest_caches_payload(monkeypatch) -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    out1 = _call_route()
    assert out1.outcome_count == 0
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (120s).
    assert fake.setex_calls[0][1] == 120

    out2 = _call_route()
    assert out2.outcome_count == 0
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_outcomes_digest_cache_isolated_per_user(
    monkeypatch,
) -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_route(current_user_id=42)
    _call_route(current_user_id=99)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_outcomes_digest_cache_isolated_per_project(
    monkeypatch,
) -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_route(project_id=1)
    _call_route(project_id=2)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_outcomes_digest_noop_when_redis_down(
    monkeypatch,
) -> None:
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types

    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object  # type: ignore[attr-defined]
        sys.modules["razorpay"] = stub

    from app.core import redis_client

    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: None,
    )

    for _ in range(2):
        out = _call_route()
        assert out.outcome_count == 0


def test_outcomes_digest_namespace_consistency() -> None:
    """Pin that the namespace constant in outcomes.py is
    used by every invalidation site (write, both outcome
    POSTs, and the DELETE)."""
    from app.api.v1 import outcomes as out_mod

    namespace = out_mod._OUTCOMES_DIGEST_CACHE_NAMESPACE
    assert namespace == "project-outcomes-digest"

    import inspect

    src = inspect.getsource(out_mod)
    # Read path + 3 invalidation sites (POST outcome-feedback,
    # POST outcomes, DELETE outcomes) must all use the constant.
    assert src.count(f"namespace={namespace}") >= 4

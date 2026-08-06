"""Route-level tests for the /me/recent-outcomes cache.

Pins: cache hit short-circuit, per-user key isolation,
Redis-down no-op, and namespace-string consistency
between the read path (users.py) and the 2 invalidation
modules (outcomes.py x3, users.py clear-archive).
"""
from __future__ import annotations

import pytest


def _patch_redis(monkeypatch, fake):
    from app.core import redis_client
    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: fake,
    )


class _FakeRedis:
    def __init__(self):
        self.store = {}
        self.setex_calls = []

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl_seconds, value):
        self.setex_calls.append((key, ttl_seconds, value))
        self.store[key] = value

    def scan_iter(self, match):
        prefix = match.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def delete(self, *keys):
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

    def count(self):
        return 0


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


class _FakeUser:
    def __init__(self):
        self.id = 42


def _call_route(current_user_id=42):
    from app.api.v1 import users as users_mod
    u = _FakeUser()
    u.id = current_user_id
    return users_mod.get_recent_outcomes(
        db=_FakeSession(),
        current_user=u,
    )


def test_recent_outcomes_caches_payload(monkeypatch):
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object
        sys.modules["razorpay"] = stub

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    out1 = _call_route()
    assert out1.outcome_count == 0
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (60s).
    assert fake.setex_calls[0][1] == 60

    out2 = _call_route()
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_recent_outcomes_cache_isolated_per_user(monkeypatch):
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object
        sys.modules["razorpay"] = stub

    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    _call_route(current_user_id=42)
    _call_route(current_user_id=99)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_recent_outcomes_noop_when_redis_down(monkeypatch):
    pytest.importorskip(
        "scipy", reason="Route registration requires scipy",
    )
    import sys
    import types
    if "razorpay" not in sys.modules:
        stub = types.ModuleType("razorpay")
        stub.Client = object
        sys.modules["razorpay"] = stub

    from app.core import redis_client
    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: None,
    )

    for _ in range(2):
        out = _call_route()
        assert out.outcome_count == 0


def test_recent_outcomes_namespace_constant_export():
    """Pin that the constant is importable from users.py."""
    from app.api.v1.users import (
        _USER_RECENT_OUTCOMES_CACHE_NAMESPACE,
    )
    assert (
        _USER_RECENT_OUTCOMES_CACHE_NAMESPACE
        == "user-recent-outcomes"
    )


def test_recent_outcomes_namespace_consistency_across_modules():
    """Pin that the 2 invalidation modules (outcomes.py
    x3, users.py clear-archive) import and use the
    constant (not a hardcoded string).
    """
    import inspect

    from app.api.v1 import users as users_mod
    from app.api.v1 import outcomes as out_mod

    namespace = users_mod._USER_RECENT_OUTCOMES_CACHE_NAMESPACE
    assert namespace == "user-recent-outcomes"

    for src, label in (
        (out_mod, "outcomes.py"),
        (users_mod, "users.py"),
    ):
        s = inspect.getsource(src)
        assert (
            "_USER_RECENT_OUTCOMES_CACHE_NAMESPACE" in s
        ), (
            f"_USER_RECENT_OUTCOMES_CACHE_NAMESPACE not "
            f"imported in {label}"
        )
        assert (
            f'namespace="{namespace}"' not in s
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

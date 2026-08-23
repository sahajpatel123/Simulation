"""Route-level tests for the /me/runs-this-month cache.

Pins: cache hit short-circuit, per-user key isolation,
Redis-down no-op, and namespace-string consistency
between the read path (users.py) and the 2 invalidation
sites (users.py clear-archive, simulations.py).
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
        self.tier = "FREE"
        self.created_at = None


def _call_route(current_user_id=42):
    from app.api.v1 import users as users_mod
    u = _FakeUser()
    u.id = current_user_id
    return users_mod.get_runs_this_month(
        db=_FakeSession(),
        current_user=u,
    )


def test_runs_this_month_caches_payload(monkeypatch):
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
    # Default FREE tier has 2 sims/month cap.
    assert out1.tier == "FREE"
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (30s).
    assert fake.setex_calls[0][1] == 30

    out2 = _call_route()
    assert out2 == out1
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_runs_this_month_cache_isolated_per_user(monkeypatch):
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


def test_runs_this_month_noop_when_redis_down(monkeypatch):
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
        # Cold recompute each time when Redis is down.
        assert out.tier == "FREE"


def test_runs_this_month_namespace_constant_export():
    """Pin that the constant is importable from users.py."""
    from app.api.v1.users import (
        _USER_RUNS_THIS_MONTH_CACHE_NAMESPACE,
    )
    assert (
        _USER_RUNS_THIS_MONTH_CACHE_NAMESPACE
        == "user-runs-this-month"
    )


def test_runs_this_month_namespace_consistency_across_modules():
    """Pin that both invalidation sites (simulations.py
    POST /simulations, users.py clear-archive) import
    and use the constant (not a hardcoded string).
    """
    import inspect

    from app.api.v1 import simulations as sim_mod
    from app.api.v1 import users as users_mod

    namespace = users_mod._USER_RUNS_THIS_MONTH_CACHE_NAMESPACE
    assert namespace == "user-runs-this-month"

    for src, label in (
        (sim_mod, "simulations.py"),
        (users_mod, "users.py"),
    ):
        s = inspect.getsource(src)
        assert (
            "_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE" in s
        ), (
            f"_USER_RUNS_THIS_MONTH_CACHE_NAMESPACE not "
            f"imported in {label}"
        )
        assert (
            f'namespace="{namespace}"' not in s
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

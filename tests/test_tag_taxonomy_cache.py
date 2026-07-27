"""Route-level tests for the /me/tag-taxonomy cache.

Pins: cache hit short-circuit, per-user key isolation,
Redis-down no-op, and namespace-string consistency
between the read path (users.py) and the clear-archive
invalidation site.
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


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()

    def execute(self, *args, **kwargs):
        return _FakeQuery()


class _FakeUser:
    def __init__(self):
        self.id = 42


def _call_route(current_user_id=42):
    from app.api.v1 import users as users_mod
    u = _FakeUser()
    u.id = current_user_id
    return users_mod.get_tag_taxonomy(
        db=_FakeSession(),
        current_user=u,
    )


def test_tag_taxonomy_caches_payload(monkeypatch):
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
    assert out1.tag_count == 0
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (300s).
    assert fake.setex_calls[0][1] == 300

    out2 = _call_route()
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_tag_taxonomy_cache_isolated_per_user(monkeypatch):
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


def test_tag_taxonomy_noop_when_redis_down(monkeypatch):
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
        assert out.tag_count == 0


def test_tag_taxonomy_namespace_constant_export():
    """Pin that the constant is importable from users.py."""
    from app.api.v1.users import (
        _USER_TAG_TAXONOMY_CACHE_NAMESPACE,
    )
    assert (
        _USER_TAG_TAXONOMY_CACHE_NAMESPACE
        == "user-tag-taxonomy"
    )


def test_tag_taxonomy_namespace_in_route_only():
    """Single read path. Invalidation is in the same
    file (users.py clear-archive). Pin the namespace
    string usage.
    """
    import inspect
    from app.api.v1 import users as users_mod

    namespace = users_mod._USER_TAG_TAXONOMY_CACHE_NAMESPACE
    assert namespace == "user-tag-taxonomy"

    src = inspect.getsource(users_mod)
    assert (
        "_USER_TAG_TAXONOMY_CACHE_NAMESPACE" in src
    )
    # Read path uses cache_get_json + cache_set_json,
    # write path uses cache_invalidate. >= 3 source
    # references to the constant.
    assert src.count(f"namespace={namespace}") >= 3

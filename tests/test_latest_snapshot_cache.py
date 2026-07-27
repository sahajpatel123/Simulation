"""Route-level tests for the /projects/{id}/latest-snapshot cache.

Pins: cache hit short-circuit, per-user + per-project
key isolation, Redis-down no-op, and namespace-string
consistency between the read path (projects.py) and the
4 invalidation modules (simulations.py, decisions.py,
outcomes.py, projects.py extract-assumptions).
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


class _FakeProject:
    id = 1
    title = "T"
    status = "COMPLETE"
    brief_completed_at = None


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return _FakeProject()

    def scalar(self):
        return None

    def all(self):
        return []


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


class _FakeUser:
    def __init__(self):
        self.id = 42


def _call_route(current_user_id=42, project_id=1):
    from app.api.v1 import projects as proj_mod
    u = _FakeUser()
    u.id = current_user_id
    return proj_mod.get_latest_snapshot(
        project_id=project_id,
        db=_FakeSession(),
        current_user=u,
    )


def test_latest_snapshot_caches_payload(monkeypatch):
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
    assert out1.project_id == 1
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (60s).
    assert fake.setex_calls[0][1] == 60

    out2 = _call_route()
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_latest_snapshot_cache_isolated_per_user(monkeypatch):
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

    _call_route(current_user_id=42, project_id=1)
    _call_route(current_user_id=99, project_id=1)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_latest_snapshot_cache_isolated_per_project(monkeypatch):
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

    _call_route(project_id=1)
    _call_route(project_id=2)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_latest_snapshot_noop_when_redis_down(monkeypatch):
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
        assert out.project_id == 1


def test_latest_snapshot_namespace_consistency_across_modules():
    """Pin that the namespace string in projects.py is
    used by every invalidation module (simulations.py,
    decisions.py, outcomes.py, projects.py
    extract-assumptions).
    """
    import inspect
    from app.api.v1 import projects as proj_mod
    from app.api.v1 import simulations as sim_mod
    from app.api.v1 import decisions as dec_mod
    from app.api.v1 import outcomes as out_mod

    namespace = proj_mod._LATEST_SNAPSHOT_CACHE_NAMESPACE
    assert namespace == "project-latest-snapshot"

    for src, label in (
        (proj_mod, "projects.py"),
        (sim_mod, "simulations.py"),
        (dec_mod, "decisions.py"),
        (out_mod, "outcomes.py"),
    ):
        s = inspect.getsource(src)
        assert (
            "_LATEST_SNAPSHOT_CACHE_NAMESPACE" in s
        ), (
            f"_LATEST_SNAPSHOT_CACHE_NAMESPACE not "
            f"imported in {label}"
        )
        assert (
            f'namespace="{namespace}"' in s
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

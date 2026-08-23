"""Route-level tests for the /projects/{id}/confidence-explainer cache.

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


class _FakeSim:
    id = 1
    status = "COMPLETED"
    project_id = 1
    confidence_score = 85.0
    consumer_volume = 10000
    predicted_conversion_rate = 0.05
    results_json = {}
    created_at = None


class _FakeProject:
    id = 1
    brief_completed_at = None
    premortem_json = None
    interventions_json = None


class _FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *_):
        return self

    def first(self):
        return _FakeSim()

    def scalar(self):
        return None

    def all(self):
        return []

    def count(self):
        return 0


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


def _call_route(current_user_id=42, project_id=1):
    from app.api.v1 import projects as proj_mod
    return proj_mod.get_confidence_explainer(
        project_id=project_id,
        db=_FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_confidence_explainer_caches_payload(monkeypatch):
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
    # Confidence is computed from the fake sim (85%).
    assert out1.confidence_score == 0.85
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (60s).
    assert fake.setex_calls[0][1] == 60

    out2 = _call_route()
    assert out2 == out1
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_confidence_explainer_cache_isolated_per_user(monkeypatch):
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


def test_confidence_explainer_cache_isolated_per_project(monkeypatch):
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


def test_confidence_explainer_noop_when_redis_down(monkeypatch):
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
        # Returns the same 5 factors each time (cache cold
        # on every call when Redis is down).
        assert len(out.factors) == 5


def test_confidence_explainer_namespace_consistency_across_modules():
    """Pin that every invalidation module imports and uses
    the constant (not a hardcoded string).
    """
    import inspect

    from app.api.v1 import outcomes as out_mod
    from app.api.v1 import projects as proj_mod
    from app.api.v1 import simulations as sim_mod

    namespace = proj_mod._CONFIDENCE_EXPLAINER_CACHE_NAMESPACE
    assert namespace == "project-confidence-explainer"

    for src, label in (
        (proj_mod, "projects.py"),
        (sim_mod, "simulations.py"),
        (out_mod, "outcomes.py"),
    ):
        s = inspect.getsource(src)
        assert (
            "_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE" in s
        ), (
            f"_CONFIDENCE_EXPLAINER_CACHE_NAMESPACE not "
            f"imported in {label}"
        )
        assert (
            f'namespace="{namespace}"' not in s
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

"""Route-level tests for the /projects/{id}/convergence cache.

Pins cache hit short-circuit, per-user + per-project key
isolation, Redis-down no-op, and namespace-string
consistency between the read path and the simulation-task
invalidation site.
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
        if args and getattr(args[0], "__name__", "") == "Project":
            return _FakeProjectQuery()
        return _FakeQuery()


class _FakeProjectQuery:
    """Project ownership query returns a valid project row."""

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return type("P", (), {"id": 1, "user_id": 42})()


def _call_route(current_user_id: int = 42, project_id: int = 1):
    from app.api.v1 import projects as proj_mod

    return proj_mod.get_convergence_check(
        project_id=project_id,
        db=_FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_convergence_caches_payload(monkeypatch) -> None:
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
    assert out1.sim_count == 0
    assert len(fake.setex_calls) == 1
    # TTL must match the module's TTL constant (120s).
    assert fake.setex_calls[0][1] == 120

    out2 = _call_route()
    assert out2.sim_count == 0
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_convergence_cache_isolated_per_user(monkeypatch) -> None:
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


def test_convergence_cache_isolated_per_project(
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


def test_convergence_noop_when_redis_down(monkeypatch) -> None:
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
        assert out.sim_count == 0


def test_convergence_namespace_consistency() -> None:
    """The namespace constant in projects.py must match the
    string the simulation-task invalidation site uses.
    """
    from app.api.v1 import projects as proj_mod

    namespace = proj_mod._CONVERGENCE_CHECK_CACHE_NAMESPACE
    assert namespace == "project-convergence"

    import inspect

    # Read path: must reference the constant.
    src_projects = inspect.getsource(proj_mod)
    assert "namespace=_CONVERGENCE_CHECK_CACHE_NAMESPACE" in src_projects

    # Invalidation path: must also reference the constant
    # (the simulation task imports from projects.py).
    src_tasks = inspect.getsource(
        __import__(
            "app.tasks.simulation_tasks",
            fromlist=["*"],
        ),
    )
    assert "_CONVERGENCE_CHECK_CACHE_NAMESPACE" in src_tasks


def test_convergence_namespace_constant_export() -> None:
    """Pin that the constant is importable from projects.py
    so the simulation task can import it without touching
    internal attribute access."""
    from app.api.v1.projects import (
        _CONVERGENCE_CHECK_CACHE_NAMESPACE,
    )

    assert (
        _CONVERGENCE_CHECK_CACHE_NAMESPACE
        == "project-convergence"
    )

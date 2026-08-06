"""Route-level tests for the /projects/{id}/next-action cache.

Mirrors the cache-isolation tests for /portfolio-narrative
and /projects/{id}/decision-digest: the route must
short-circuit on hit, isolate by user + project, and
silently no-op when Redis is unavailable.
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
    """Minimal Query stub — just enough for the route's
    three SELECTs. ``all()`` returns [] for everything
    so the helper gets the priority-4/first_sim fallback."""

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

    return proj_mod.get_next_action(
        project_id=project_id,
        db=_FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_next_action_caches_payload(monkeypatch) -> None:
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

    # First call → cache populated.
    out1 = _call_route()
    assert out1.category == "first_sim"
    assert len(fake.setex_calls) == 1
    assert fake.setex_calls[0][1] == 60  # TTL

    # Second call → cache hit, no new SETEX (the route
    # returns from the early-return branch so the helper
    # isn't even invoked).
    out2 = _call_route()
    assert out2.category == "first_sim"
    assert len(fake.setex_calls) == 1  # unchanged


def test_next_action_cache_isolated_per_user(monkeypatch) -> None:
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


def test_next_action_cache_isolated_per_project(monkeypatch) -> None:
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


def test_next_action_noop_when_redis_down(monkeypatch) -> None:
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

    # Two calls; both must succeed.
    for _ in range(2):
        out = _call_route()
        assert out.category == "first_sim"


def test_cache_namespace_consistency() -> None:
    """The cache namespace string in projects.py must match
    the strings the invalidation sites use, otherwise
    invalidation never lands."""
    # Read the namespace constant from projects.py and the
    # invalidation literal from each callsite.
    from app.api.v1 import projects as proj_mod
    from app.api.v1 import simulations as sim_mod
    from app.api.v1 import decisions as dec_mod

    namespace = proj_mod._NEXT_ACTION_CACHE_NAMESPACE
    assert namespace == "project-next-action"

    # Grep for the literal in the right places. Use a
    # tiny string scan so we don't depend on imports of
    # the task files (which need celery running).
    import inspect

    src_projects = inspect.getsource(proj_mod)
    src_simulations = inspect.getsource(sim_mod)
    src_decisions = inspect.getsource(dec_mod)

    # Each invalidation site that we documented above
    # must use the exact namespace string.
    for src, label in (
        (src_projects, "projects.py (read path)"),
        (src_simulations, "simulations.py (POST)"),
        (src_decisions, "decisions.py (POST)"),
    ):
        assert "namespace=_NEXT_ACTION_CACHE_NAMESPACE" in src, (
            f"namespace mismatch in {label}"
        )

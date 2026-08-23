"""Route-level tests for the /projects/{id}/stale-check cache.

Pins: cache hit short-circuit, per-user + per-project
key isolation, Redis-down no-op, and namespace-string
consistency between the read path (projects.py) and the
invalidation sites in projects.py + simulations.py +
decisions.py + outcomes.py.
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


class _FakeProject:
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
        return None

    def scalar(self):
        return None

    def all(self):
        return []

    def count(self):
        return 0


class _FakeProjectQuery:
    """Project ownership query returns a valid project row."""

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return _FakeProject()


class _FakeSession:
    def query(self, *args, **kwargs):
        if args and getattr(args[0], "__name__", "") == "Project":
            return _FakeProjectQuery()
        return _FakeQuery()


def _call_route(current_user_id: int = 42, project_id: int = 1):
    from app.api.v1 import projects as proj_mod

    return proj_mod.get_stale_check(
        project_id=project_id,
        db=_FakeSession(),
        current_user=type("U", (), {"id": current_user_id})(),
    )


def test_stale_check_caches_payload(monkeypatch) -> None:
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
    assert out1.stale_count == 6  # 6 sources None
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (60s).
    assert fake.setex_calls[0][1] == 60

    out2 = _call_route()
    assert out2 == out1
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_stale_check_cache_isolated_per_user(monkeypatch) -> None:
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


def test_stale_check_cache_isolated_per_project(monkeypatch) -> None:
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


def test_stale_check_noop_when_redis_down(monkeypatch) -> None:
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
        assert out.sources_checked == 6


def test_stale_check_namespace_consistency_across_modules() -> None:
    """The namespace string in projects.py is the single
    source of truth - both the read path and every
    invalidation site (in projects.py + simulations.py +
    decisions.py + outcomes.py) must use the constant.
    """
    import inspect

    from app.api.v1 import decisions as dec_mod
    from app.api.v1 import outcomes as out_mod
    from app.api.v1 import projects as proj_mod
    from app.api.v1 import simulations as sim_mod

    namespace = proj_mod._STALE_CHECK_CACHE_NAMESPACE
    assert namespace == "project-stale-check"

    for src, label in (
        (proj_mod, "projects.py"),
        (sim_mod, "simulations.py"),
        (dec_mod, "decisions.py"),
        (out_mod, "outcomes.py"),
    ):
        s = inspect.getsource(src)
        assert (
            "_STALE_CHECK_CACHE_NAMESPACE" in s
        ), (
            f"_STALE_CHECK_CACHE_NAMESPACE not imported "
            f"in {label}"
        )
        assert (
            f'namespace="{namespace}"' not in s
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

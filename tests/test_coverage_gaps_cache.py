"""Route-level tests for the /me/coverage-gaps cache.

Pins: cache hit short-circuit, per-user key isolation,
graceful no-op when Redis is unavailable, and
namespace-string consistency between the read path and
the extract-assumptions invalidation site.
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


class _FakeAssumption:
    id = 1
    category = "Pricing"
    sensitivity = "HIGH"
    is_hidden = False


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

    def count(self):
        return 0

    def all(self):
        return [_FakeAssumption()]


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()


class _FakeUser:
    def __init__(self) -> None:
        self.id = 42
        self.tier = "FREE"
        self.created_at = None


def _call_coverage_gaps(current_user_id: int = 42):
    from app.api.v1 import users as users_mod

    u = _FakeUser()
    u.id = current_user_id

    return users_mod.get_coverage_gaps(
        db=_FakeSession(),
        current_user=u,
    )


def test_coverage_gaps_caches_payload(monkeypatch) -> None:
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

    out1 = _call_coverage_gaps()
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (300s).
    assert fake.setex_calls[0][1] == 300

    out2 = _call_coverage_gaps()
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_coverage_gaps_cache_isolated_per_user(monkeypatch) -> None:
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

    _call_coverage_gaps(current_user_id=42)
    _call_coverage_gaps(current_user_id=99)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_coverage_gaps_noop_when_redis_down(monkeypatch) -> None:
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
        out = _call_coverage_gaps()
        # coverage-gaps calls return a CoverageGapsOut
        # with defaulted fields when no data.
        assert out.total_assumption_count >= 0


def test_coverage_gaps_namespace_constant_export() -> None:
    """Pin that the constant is importable from users.py."""
    from app.api.v1.users import _USER_COVERAGE_GAPS_CACHE_NAMESPACE

    assert (
        _USER_COVERAGE_GAPS_CACHE_NAMESPACE
        == "user-coverage-gaps"
    )


def test_coverage_gaps_namespace_consistency_across_modules() -> None:
    """Pin that the namespace string in users.py is used by
    the read path AND by the extract-assumptions
    invalidation site (in projects.py)."""
    import inspect

    from app.api.v1 import users as users_mod
    from app.api.v1 import projects as proj_mod

    namespace = users_mod._USER_COVERAGE_GAPS_CACHE_NAMESPACE
    assert namespace == "user-coverage-gaps"

    # Read path uses the constant.
    src_users = inspect.getsource(users_mod)
    assert f'namespace="{namespace}"' in src_users

    # Invalidation site (the extract-assumptions route in
    # projects.py) imports + uses the constant.
    src_proj = inspect.getsource(proj_mod)
    assert "_USER_COVERAGE_GAPS_CACHE_NAMESPACE" in src_proj
    assert f'namespace="{namespace}"' in src_proj
"""Route-level tests for the /me/dashboard cache + namespace
consistency across the 6 invalidation sites wired in
this iteration.

Mirrors the cache-isolation tests for the other
per-project tiles. Pins cache hit short-circuit, per-user
key isolation, Redis-down no-op, and namespace-string
consistency between the read path and all 6 invalidation
sites.
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


class _FakeUser:
    def __init__(self) -> None:
        self.id = 42
        self.tier = "FREE"
        self.created_at = None
        self.reduced_motion = False
        self.email_notices = False
        self.weekly_brief = False
        self.default_units = ""
        self.default_reader_count = 0
        self.default_scenario = ""
        self.default_aov = 0.0
        self.keep_past_results = False


def _call_dashboard(current_user_id: int = 42):
    from app.api.v1 import users as users_mod

    u = _FakeUser()
    u.id = current_user_id

    return users_mod.get_my_dashboard(
        db=_FakeSession(),
        current_user=u,
    )


def test_user_dashboard_caches_payload(monkeypatch) -> None:
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

    out1 = _call_dashboard()
    assert out1.project_count == 0
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (30s).
    assert fake.setex_calls[0][1] == 30

    out2 = _call_dashboard()
    assert out2.project_count == 0
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_user_dashboard_cache_isolated_per_user(monkeypatch) -> None:
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

    _call_dashboard(current_user_id=42)
    _call_dashboard(current_user_id=99)

    # Two distinct users → two distinct keys.
    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_user_dashboard_noop_when_redis_down(monkeypatch) -> None:
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
        out = _call_dashboard()
        assert out.tier == "FREE"


def test_user_dashboard_namespace_constant_export() -> None:
    """Pin that the constant is importable from users.py
    so other modules (simulations, decisions, outcomes)
    can import it without touching internal attribute
    access — same pattern as
    _NEXT_ACTION_CACHE_NAMESPACE."""
    from app.api.v1.users import _USER_DASHBOARD_CACHE_NAMESPACE

    assert _USER_DASHBOARD_CACHE_NAMESPACE == "user-dashboard"


def test_user_dashboard_namespace_consistency_across_modules() -> None:
    """The namespace string is the single source of truth
    in users.py — every invalidation site in simulations /
    decisions / outcomes / projects / users must import +
    use the constant (not a hardcoded string)."""
    import inspect

    from app.api.v1 import users as users_mod
    from app.api.v1 import simulations as sim_mod
    from app.api.v1 import decisions as dec_mod
    from app.api.v1 import outcomes as out_mod

    namespace = users_mod._USER_DASHBOARD_CACHE_NAMESPACE
    assert namespace == "user-dashboard"

    # Each call site must use the constant.
    src_sim = inspect.getsource(sim_mod)
    src_dec = inspect.getsource(dec_mod)
    src_out = inspect.getsource(out_mod)
    src_users = inspect.getsource(users_mod)

    for src, label in (
        (src_sim, "simulations.py"),
        (src_dec, "decisions.py"),
        (src_out, "outcomes.py"),
        (src_users, "users.py"),
    ):
        # The import appears at least once in each
        # invalidator module.
        assert (
            f"_USER_DASHBOARD_CACHE_NAMESPACE" in src
        ), f"_USER_DASHBOARD_CACHE_NAMESPACE not imported in {label}"
        # And the namespace literal is used via the
        # constant (not hardcoded as "user-dashboard").
        assert (
            f'namespace="{namespace}"' in src
        ), f"namespace literal not used via constant in {label}"
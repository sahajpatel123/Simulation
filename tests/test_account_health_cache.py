"""Route-level tests for the /me/account-health cache.

Pins: cache hit short-circuit, per-user key isolation,
graceful no-op when Redis is unavailable, and
namespace-string consistency between the read path and
all 5 invalidation sites (POST /simulations, POST
/decisions, POST /outcome-feedback, POST /outcomes,
DELETE /outcomes, POST /me/clear-archive).
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
        return 0

    def all(self):
        return []


class _FakeSession:
    def query(self, *args, **kwargs):
        return _FakeQuery()

    def execute(self, *args, **kwargs):
        return type("R", (), {
            "fetchall": lambda self=0: [],
            "scalar": lambda self=0: 0,
        })()


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


def _call_account_health(current_user_id: int = 42):
    from app.api.v1 import users as users_mod

    u = _FakeUser()
    u.id = current_user_id

    return users_mod.get_account_health(
        db=_FakeSession(),
        current_user=u,
    )


def test_account_health_caches_payload(monkeypatch) -> None:
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

    out1 = _call_account_health()
    assert len(fake.setex_calls) == 1
    # TTL must match the route's TTL (60s).
    assert fake.setex_calls[0][1] == 60

    out2 = _call_account_health()
    assert out2 == out1
    assert len(fake.setex_calls) == 1  # hit, no new SETEX


def test_account_health_cache_isolated_per_user(monkeypatch) -> None:
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

    _call_account_health(current_user_id=42)
    _call_account_health(current_user_id=99)

    assert len(fake.setex_calls) == 2
    keys = {c[0] for c in fake.setex_calls}
    assert len(keys) == 2


def test_account_health_noop_when_redis_down(monkeypatch) -> None:
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
        out = _call_account_health()
        # Health score defaults to 0 when no data and the
        # helper can't compute it under failure. Just
        # confirm the call succeeded.
        assert out.verdict == "AT_RISK"


def test_account_health_namespace_constant_export() -> None:
    """Pin that the constant is importable from users.py
    (same pattern as _USER_DASHBOARD_CACHE_NAMESPACE)."""
    from app.api.v1.users import _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE

    assert (
        _USER_ACCOUNT_HEALTH_CACHE_NAMESPACE
        == "user-account-health"
    )


def test_account_health_namespace_consistency_across_modules() -> None:
    """Pin that every invalidator imports and uses the
    constant — not a hardcoded string — so future
    renames propagate."""
    import inspect

    from app.api.v1 import decisions as dec_mod
    from app.api.v1 import outcomes as out_mod
    from app.api.v1 import simulations as sim_mod
    from app.api.v1 import users as users_mod

    namespace = users_mod._USER_ACCOUNT_HEALTH_CACHE_NAMESPACE
    assert namespace == "user-account-health"

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
        assert (
            "_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE" in src
        ), (
            f"_USER_ACCOUNT_HEALTH_CACHE_NAMESPACE not "
            f"imported in {label}"
        )
        assert (
            f'namespace="{namespace}"' not in src
        ), (
            f"namespace literal not used via constant "
            f"in {label}"
        )

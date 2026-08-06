"""Tests for the tiny Redis-backed response_cache helper.

The helper is intentionally pure-Python + side-effect-free
when Redis is unavailable, so the tests stub the redis
client via monkeypatch rather than reaching for a real
Redis instance.
"""
from __future__ import annotations

from typing import Any


class _FakeRedis:
    """Minimal in-memory redis stub with the surface the
    helper uses: ``get``, ``setex``, ``scan_iter``,
    ``delete``."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(
        self, key: str, ttl_seconds: int, value: str,
    ) -> None:  # noqa: ARG002 — ttl exercised via real redis
        self.store[key] = value

    def scan_iter(self, match: str) -> list[str]:
        # ``match`` is treated as a prefix in this stub
        # because that's all the helper needs.
        prefix = match.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]

    def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n


def _patch_redis(monkeypatch, fake: _FakeRedis) -> None:
    from app.core import redis_client

    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: fake,
    )


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def test_cache_set_then_get_round_trips(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_get_json,
        cache_set_json,
    )

    payload: dict[str, Any] = {
        "narrative": "hello",
        "key_signals": [{"label": "mae", "value": 0.04}],
        "recommended_actions": [],
    }
    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [1, 2, 3]},
            user_id=42,
        )
        is None
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1, 2, 3]},
        user_id=42,
        value=payload,
        ttl_seconds=30,
    )

    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [1, 2, 3]},
            user_id=42,
        )
        == payload
    )


def test_cache_miss_distinct_user(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_get_json,
        cache_set_json,
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1, 2, 3]},
        user_id=42,
        value={"narrative": "for user 42"},
        ttl_seconds=30,
    )
    # Different user → must miss, never leak.
    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [1, 2, 3]},
            user_id=99,
        )
        is None
    )


def test_cache_miss_distinct_namespace(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_get_json,
        cache_set_json,
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1, 2, 3]},
        user_id=42,
        value={"narrative": "x"},
        ttl_seconds=30,
    )
    # Different namespace → same params, different key.
    assert (
        cache_get_json(
            namespace="other-endpoint",
            params={"ids": [1, 2, 3]},
            user_id=42,
        )
        is None
    )


def test_cache_key_independent_of_param_order(monkeypatch) -> None:
    """Equivalent param dicts (same set, different order)
    must collapse to the same cache key so two clients that
    serialise ids in a different order still hit the cache.
    """
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_get_json,
        cache_set_json,
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1, 2, 3]},
        user_id=42,
        value={"narrative": "hello"},
        ttl_seconds=30,
    )
    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [3, 2, 1]},
            user_id=42,
        )
        == {"narrative": "hello"}
    )


def test_cache_corrupt_payload_returns_none(monkeypatch) -> None:
    """A non-JSON value in the cache must not raise — the
    helper returns None so the caller recomputes."""
    fake = _FakeRedis()
    fake.store["rcache:portfolio-narrative:42:abc"] = (
        "not-json-at-all"
    )
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import cache_get_json

    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [1]},
            user_id=42,
        )
        is None
    )


def test_cache_noop_when_redis_unavailable(monkeypatch) -> None:
    """When get_redis_client returns None (dev, tests,
    CI), the helper must silently no-op rather than raise
    so routes keep working."""
    from app.core import redis_client

    monkeypatch.setattr(
        redis_client, "get_redis_client", lambda: None,
    )

    from app.core.response_cache import (
        cache_get_json,
        cache_set_json,
    )

    # Should not raise.
    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1]},
        user_id=42,
        value={"narrative": "x"},
        ttl_seconds=30,
    )
    assert (
        cache_get_json(
            namespace="portfolio-narrative",
            params={"ids": [1]},
            user_id=42,
        )
        is None
    )


def test_cache_set_swallows_redis_error(monkeypatch) -> None:
    """A setex failure (connection lost, etc.) must not
    propagate — the caller should fall through to its own
    computation."""

    class _BrokenRedis(_FakeRedis):
        def setex(self, *args, **kwargs) -> None:  # type: ignore[override]
            raise ConnectionError("redis offline")

    _patch_redis(monkeypatch, _BrokenRedis())

    from app.core.response_cache import cache_set_json

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1]},
        user_id=42,
        value={"narrative": "x"},
        ttl_seconds=30,
    )


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_cache_invalidate_user_scope(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_invalidate,
        cache_set_json,
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1]},
        user_id=42,
        value={"narrative": "x"},
        ttl_seconds=30,
    )
    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [2]},
        user_id=99,
        value={"narrative": "y"},
        ttl_seconds=30,
    )

    n = cache_invalidate(
        namespace="portfolio-narrative", user_id=42,
    )
    assert n == 1
    assert fake.store == {
        "rcache:portfolio-narrative:99:"
        "45cd05795350fadf": '{"narrative": "y"}',
    }


def test_cache_invalidate_namespace_scope(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import (
        cache_invalidate,
        cache_set_json,
    )

    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": [1]},
        user_id=42,
        value={"narrative": "x"},
        ttl_seconds=30,
    )
    cache_set_json(
        namespace="other-endpoint",
        params={"ids": [1]},
        user_id=42,
        value={"narrative": "z"},
        ttl_seconds=30,
    )

    n = cache_invalidate(namespace="portfolio-narrative")
    assert n == 1
    # Other namespace survives.
    assert any(
        k.startswith("rcache:other-endpoint:")
        for k in fake.store
    )


def test_cache_invalidate_empty_returns_zero(monkeypatch) -> None:
    fake = _FakeRedis()
    _patch_redis(monkeypatch, fake)

    from app.core.response_cache import cache_invalidate

    assert (
        cache_invalidate(namespace="does-not-exist", user_id=42)
        == 0
    )

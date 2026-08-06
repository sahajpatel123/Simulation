"""Tiny JSON response cache backed by Redis.

Use when an endpoint does non-trivial work (multiple
sub-helpers, joins, expensive aggregations) and is likely
to be polled by the dashboard within a short window. The
TTL is intentionally short (default 30s) — long enough to
absorb dashboard polls, short enough that new simulation
results are reflected promptly.

Design notes
------------
* Graceful: when Redis is unavailable (``get_redis_client``
  returns ``None``) the cache is a silent no-op so routes
  keep working in dev / unit-test environments.
* Per-user: the cache key is namespaced by user id so one
  tenant's payload never leaks to another.
* Pure-Python: no decorators, no thread-locals. The caller
  composes the key and decides what to do on hit / miss —
  keeps the helper testable and obvious.

Typical use
-----------
::

    payload = cache_get_json(
        namespace="portfolio-narrative",
        params={"ids": canonical_ids},
        user_id=current_user.id,
    )
    if payload is not None:
        return PortfolioNarrativeOut(**payload)
    payload = build_portfolio_narrative(...)
    cache_set_json(
        namespace="portfolio-narrative",
        params={"ids": canonical_ids},
        user_id=current_user.id,
        value=payload,
        ttl_seconds=30,
    )
    return PortfolioNarrativeOut(**payload)
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.core import redis_client

logger = logging.getLogger(__name__)


def _normalise(value: Any) -> Any:
    """Recursively canonicalise a param value so equivalent
    dicts/lists hash identically regardless of ordering."""
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted(
            (_normalise(v) for v in value),
            key=lambda v: json.dumps(v, sort_keys=True, default=str),
        )
    return value


def _stable_hash(payload: dict[str, Any]) -> str:
    """Deterministic short hash so two equivalent param
    dicts (e.g. ``{"ids": [1, 2]}`` vs ``{"ids": [2, 1]}``)
    collapse to the same cache key."""
    serialised = json.dumps(
        _normalise(payload),
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]


def _build_key(
    namespace: str,
    params: dict[str, Any],
    user_id: int | str,
) -> str:
    """Compose the Redis key.

    Format: ``rcache:<namespace>:<user_id>:<params_hash>``.
    Keeping the namespace first makes it trivial to scan /
    invalidate a single endpoint's keys in dev with
    ``KEYS rcache:portfolio-narrative:*``.
    """
    return (
        f"rcache:{namespace}:{user_id}:{_stable_hash(params)}"
    )


def cache_get_json(
    namespace: str,
    params: dict[str, Any],
    user_id: int | str,
) -> dict[str, Any] | None:
    """Read a cached JSON payload. Returns ``None`` on miss
    or on any Redis error (logged at warning level)."""
    client = redis_client.get_redis_client()
    if client is None:
        return None
    key = _build_key(namespace, params, user_id)
    try:
        raw = client.get(key)
    except Exception as exc:
        logger.warning("response_cache get failed: %s", exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "response_cache: corrupt payload at %s — %s", key, exc
        )
        return None


def cache_set_json(
    namespace: str,
    params: dict[str, Any],
    user_id: int | str,
    value: dict[str, Any],
    ttl_seconds: int = 30,
) -> None:
    """Write a JSON payload with TTL. Silently no-ops on
    Redis failure so callers don't need to wrap."""
    client = redis_client.get_redis_client()
    if client is None:
        return
    key = _build_key(namespace, params, user_id)
    try:
        client.setex(
            key,
            ttl_seconds,
            json.dumps(value, default=str),
        )
    except Exception as exc:
        logger.warning("response_cache set failed: %s", exc)


def cache_invalidate(
    namespace: str,
    user_id: int | str | None = None,
) -> int:
    """Best-effort cache invalidation. Returns the number
    of keys removed (0 if Redis is unavailable).

    When ``user_id`` is given, only that user's keys for the
    namespace are purged. When ``None``, ALL users for the
    namespace are purged via a pattern delete.
    """
    client = redis_client.get_redis_client()
    if client is None:
        return 0
    if user_id is None:
        pattern = f"rcache:{namespace}:*"
        try:
            keys = list(client.scan_iter(match=pattern))
            if not keys:
                return 0
            return int(client.delete(*keys))
        except Exception as exc:
            logger.warning(
                "response_cache invalidate(pattern) failed: %s", exc
            )
            return 0
    pattern = f"rcache:{namespace}:{user_id}:*"
    try:
        keys = list(client.scan_iter(match=pattern))
        if not keys:
            return 0
        return int(client.delete(*keys))
    except Exception as exc:
        logger.warning("response_cache invalidate failed: %s", exc)
        return 0


__all__ = [
    "cache_get_json",
    "cache_set_json",
    "cache_invalidate",
]

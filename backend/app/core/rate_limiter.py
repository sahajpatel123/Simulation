from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """
    Simple sliding window rate limiter.
    Production: replace with Redis-backed limiter.
    """

    def __init__(self) -> None:
        self._requests: dict[str, list[datetime]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(
        self,
        key: str,
        limit: int,
        window_s: int,
    ) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=window_s)
        with self._lock:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
            if len(self._requests[key]) >= limit:
                return False
            self._requests[key].append(now)
            return True


class RedisRateLimiter:
    def __init__(self) -> None:
        self._client = get_redis_client()

    def is_allowed(self, key: str, limit: int, window_s: int) -> bool | None:
        if self._client is None:
            return None

        now_ms = int(time.time() * 1000)
        window_ms = window_s * 1000
        entry_id = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            allowed = self._client.eval(
                """
                redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1] - ARGV[2])
                local current = redis.call('ZCARD', KEYS[1])
                if current >= tonumber(ARGV[3]) then
                  redis.call('EXPIRE', KEYS[1], ARGV[4])
                  return 0
                end
                redis.call('ZADD', KEYS[1], ARGV[1], ARGV[5])
                redis.call('EXPIRE', KEYS[1], ARGV[4])
                return 1
                """,
                1,
                key,
                now_ms,
                window_ms,
                limit,
                window_s,
                entry_id,
            )
            return bool(allowed)
        except Exception as exc:
            logger.warning("Redis rate limit fallback for %s: %s", key, exc)
            return None


_memory_limiter = InMemoryRateLimiter()
_redis_limiter = RedisRateLimiter()


def rate_limit(limit: int = 30, window_s: int = 60):
    """
    FastAPI dependency. Raises 429 if rate exceeded.
    Keyed by IP address + path.
    """

    async def _check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"rate-limit:{request.url.path}:{ip}"
        allowed = _redis_limiter.is_allowed(key, limit, window_s)
        if allowed is None:
            if settings.ENVIRONMENT.lower() == "production":
                # Fail closed but signal retryability to the client instead of
                # relying on the generic 500 handler.
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Rate limiting temporarily unavailable. "
                        "Redis connectivity is required in production; retry shortly."
                    ),
                    headers={"Retry-After": str(window_s)},
                )
            allowed = _memory_limiter.is_allowed(key, limit, window_s)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {limit} requests per {window_s}s.",
                headers={"Retry-After": str(window_s)},
            )

    return _check

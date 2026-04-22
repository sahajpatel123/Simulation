from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request


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


_limiter = InMemoryRateLimiter()


def rate_limit(limit: int = 30, window_s: int = 60):
    """
    FastAPI dependency. Raises 429 if rate exceeded.
    Keyed by IP address + path.
    """

    async def _check(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{request.url.path}"
        if not _limiter.is_allowed(key, limit, window_s):
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {limit} requests per {window_s}s.",
                headers={"Retry-After": str(window_s)},
            )

    return _check

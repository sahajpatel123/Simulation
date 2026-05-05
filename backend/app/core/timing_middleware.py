from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("thecee.timing")


class TimingMiddleware(BaseHTTPMiddleware):
    """
    Logs response time for every request.
    Warns on any endpoint > 500ms.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        level = logging.WARNING if elapsed > 500 else logging.DEBUG
        logger.log(level, f"{request.method} {request.url.path} → {elapsed:.1f}ms")

        response.headers["X-Response-Time"] = f"{elapsed:.1f}ms"
        return response

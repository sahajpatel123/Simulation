from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.metrics import metrics

logger = logging.getLogger("thecee.timing")


# Routes the metrics middleware should ignore. ``/metrics`` would otherwise
# pollute the request-count histogram with self-scrapes (one observation
# every scrape interval), which both skews the latency distribution and
# creates a feedback loop where scraping creates more work for the scraper.
# ``/health`` / ``/readyz`` are cheap probes that don't represent real
# application load, so we exclude them too.
_METRICS_EXEMPT_PATHS = frozenset({"/metrics", "/health", "/readyz"})


def _normalise_path(request: Request) -> str:
    """Return the matched route template for ``request`` if one exists.

    ``request.url.path`` is the raw URL (e.g. ``/projects/42/simulations/7``).
    Using that as a Prometheus label would blow up cardinality — one unique
    label set per ``id``, forever. FastAPI stores the matched route on
    ``request.scope["route"].path`` (e.g. ``/projects/{project_id}/simulations/{simulation_id}``).
    Falls back to ``"unmatched"`` when the router didn't match (404s, scanner
    traffic) so we still see them but as a single bucket.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None) if route is not None else None
    if not template:
        return "unmatched"
    return template


class TimingMiddleware(BaseHTTPMiddleware):
    """
    Logs response time for every request, warns on any endpoint > 500ms,
    and feeds the Prometheus request counter + latency histogram.

    Three labels are emitted per request:
      * ``method``  — HTTP method (GET, POST, …).
      * ``path``    — matched route template (or ``"unmatched"`` for 404s).
      * ``status``  — response status class ("2xx", "4xx", "5xx"). Using the
        class instead of the literal code keeps cardinality bounded while
        still letting dashboards compute success-rate alerts.

    Skipping the metrics path itself (``/metrics``) prevents the scrape
    loop from polluting the histogram with self-observations.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Correlation ID set by RequestIdMiddleware (outermost middleware).
        # Including it lets ops correlate a slow request with its audit row
        # and error response without grepping for a client-provided header.
        request_id = getattr(request.state, "request_id", None)

        # Status-class bucketing: 200 → "2xx", 404 → "4xx", 503 → "5xx".
        # Anything outside 100-599 falls back to "other" so a malformed
        # proxy response doesn't poison the counter.
        status_code = response.status_code
        if 100 <= status_code < 600:
            status_class = f"{status_code // 100}xx"
        else:
            status_class = "other"

        # Always log — the original behavior of this middleware.
        level = logging.WARNING if elapsed_ms > 500 else logging.DEBUG
        logger.log(
            level,
            f"{request.method} {request.url.path} → {elapsed_ms:.1f}ms "
            f"request_id={request_id}",
        )

        # Feed the metrics registry only for real application routes.
        # The exempt set bounds cardinality of ``self-scrape`` traffic and
        # stops the histogram from being dominated by health probes.
        if request.url.path not in _METRICS_EXEMPT_PATHS:
            path_label = _normalise_path(request)
            metrics.http_request(
                method=request.method,
                path=path_label,
                status=status_class,
                duration_seconds=elapsed_ms / 1000.0,
            )

        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        return response

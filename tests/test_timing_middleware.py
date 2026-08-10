"""Regression tests for ``app.core.timing_middleware``.

The middleware records request latency in the in-process
metrics registry (added in c2b3d41). The path it uses as
the histogram label is critical: using the raw URL would
blow up label cardinality (one unique label per project_id
forever), so the middleware extracts the matched route
template from ``request.scope[\"route\"]``.

These tests pin:
* ``_METRICS_EXEMPT_PATHS`` excludes /metrics, /health, /readyz and the
  request-health / query-health / cache-health digests so probe traffic
  doesn't pollute its own histogram
* ``_normalise_path`` returns the matched template, or
  ``\"unmatched\"`` for routes Starlette didn't match
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.core.timing_middleware import (
    _METRICS_EXEMPT_PATHS,
    _normalise_path,
)


def test_metrics_exempt_paths_includes_probes() -> None:
    """``/metrics``, ``/health``, ``/readyz`` and the observability digests are exempt.

    Including /metrics in the histogram would create a
    feedback loop: scraping creates observations which
    show up as 'slow requests' on dashboards which
    trigger more scraping. /health and /readyz are cheap
    probes that don't represent real application load, and the
    request-health / query-health / cache-health digests are the same —
    every dashboard poll of them would otherwise add a self-observation to
    the histogram they report on, and cache-health also scans Redis.
    """
    assert "/metrics" in _METRICS_EXEMPT_PATHS
    assert "/health" in _METRICS_EXEMPT_PATHS
    assert "/readyz" in _METRICS_EXEMPT_PATHS
    assert "/api/v1/system/request-health" in _METRICS_EXEMPT_PATHS
    assert "/api/v1/system/query-health" in _METRICS_EXEMPT_PATHS
    assert "/api/v1/system/cache-health" in _METRICS_EXEMPT_PATHS


def test_normalise_path_returns_template_when_route_matches() -> None:
    """When Starlette has matched a route, return its
    template so the histogram buckets by template, not by
    concrete URL (e.g. /projects/{id}/health, not
    /projects/42/health — which would explode cardinality).
    """
    request = MagicMock()
    request.scope = {
        "route": MagicMock(path="/projects/{project_id}/health")
    }
    assert _normalise_path(request) == "/projects/{project_id}/health"


def test_normalise_path_returns_unmatched_when_no_route() -> None:
    """When Starlette has NOT matched a route (404 path,
    scanner traffic, or any unmapped URL), return
    ``\"unmatched\"`` so the histogram bucketing stays
    bounded — millions of unique scan URLs would otherwise
    each get their own label."""
    request = MagicMock()
    request.scope = {"route": None}
    assert _normalise_path(request) == "unmatched"

    request.scope = {}
    assert _normalise_path(request) == "unmatched"


def test_normalise_path_handles_route_without_path_attr() -> None:
    """Defensive: a route object without a ``path`` attribute
    (custom routes, edge cases in FastAPI's internals) is
    treated as unmatched, not as a crash."""
    route = MagicMock(spec=[])  # no attributes at all
    request = MagicMock()
    request.scope = {"route": route}
    assert _normalise_path(request) == "unmatched"

"""Systemic guard: no route may be both unauthenticated and unlimited.

Every endpoint on the app must carry either an auth dependency or a rate
limit. Health/status probes are deliberately unauthenticated (load
balancers and Prometheus cannot present JWTs) but bounded, with
``fail_open=True`` so a limiter outage can't convert diagnostics into
failures. This suite pins that invariant across every registered route —
a new handler can no longer silently reintroduce an unbounded anonymous
surface; it fails CI until the route is guarded or explicitly allowlisted.
"""

from __future__ import annotations

import pytest

# Escape hatch for future exceptions. Every entry needs a documented
# reason — a route lands here ONLY if it is genuinely cheap/static AND
# safe to serve anonymously without bound.
DELIBERATELY_OPEN: frozenset[str] = frozenset()

AUTH_DEPENDENCY_NAMES = {"get_current_user", "get_current_user_optional", "require_admin"}

RATE_LIMITER_MODULE = "app.core.rate_limiter"


def _dependency_callables(route) -> list:
    """Every dependency callable reachable from the route.

    Router-level dependencies live on the route as ``Depends`` objects;
    the endpoint dependant holds resolved sub-dependants. Note that
    ``rate_limit()`` returns an inner ``_check`` closure, so identity is
    matched via ``__module__``, not ``__name__``.
    """
    calls = []
    for depends in getattr(route, "dependencies", []) or []:
        func = getattr(depends, "dependency", None)
        if callable(func):
            calls.append(func)
    stack = [route.dependant]
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if callable(call):
            calls.append(call)
        stack.extend(dep.dependencies)
    return calls


def _is_authenticated(route) -> bool:
    names = {getattr(c, "__name__", "") for c in _dependency_callables(route)}
    return bool(names & AUTH_DEPENDENCY_NAMES)


def _is_rate_limited(route) -> bool:
    return any(
        getattr(c, "__module__", "") == RATE_LIMITER_MODULE for c in _dependency_callables(route)
    )


def _all_api_routes(app) -> list:
    """APIRoutes at the top level plus inside deferred router includes."""
    from fastapi.routing import APIRoute

    routes = []
    for route in app.router.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        elif type(route).__name__ == "_IncludedRouter":
            # Newer FastAPI defers include_router flattening into this wrapper.
            for inner in route.original_router.routes:
                if isinstance(inner, APIRoute):
                    routes.append(inner)
                else:
                    sub = getattr(inner, "original_router", None)
                    if sub is not None:
                        routes.extend(r for r in sub.routes if isinstance(r, APIRoute))
    return routes


def _closure_values(dependency_func) -> list:
    values: list = []
    for cell in getattr(dependency_func, "__closure__", None) or ():
        try:
            values.append(cell.cell_contents)
        except ValueError:  # pragma: no cover - empty cell
            pass
    return values


def _load_app():
    pytest.importorskip("jwt")

    import sys
    import types

    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.main import app

    return app


def _routes_ending_with(app, suffix: str) -> list:
    return [r for r in _all_api_routes(app) if r.path.endswith(suffix)]


class TestNoUnboundedAnonymousSurface:
    def test_every_route_is_authenticated_or_rate_limited(self) -> None:
        app = _load_app()
        offenders = [
            (sorted(r.methods - {"HEAD", "OPTIONS"}), r.path)
            for r in _all_api_routes(app)
            if not _is_authenticated(r) and not _is_rate_limited(r)
        ]
        offenders = [o for o in offenders if o[1] not in DELIBERATELY_OPEN]
        assert not offenders, (
            "Routes below accept anonymous traffic with no rate limit — "
            f"add an auth dependency or Depends(rate_limit(...)), or "
            f"document the exception in DELIBERATELY_OPEN: {offenders}"
        )

    def test_allowlisted_paths_actually_exist(self) -> None:
        """A stale allowlist entry (route renamed/removed) must not linger
        as silent approval for whatever replaces it."""
        if not DELIBERATELY_OPEN:
            pytest.skip("allowlist empty")
        app = _load_app()
        known = {r.path for r in _all_api_routes(app)}
        unknown = DELIBERATELY_OPEN - known
        assert not unknown, f"DELIBERATELY_OPEN names nonexistent paths: {unknown}"


class TestProbeLimitsAreFailOpen:
    """Probes diagnose outages — the limiter must never gate them closed."""

    @pytest.mark.parametrize(
        ("path_suffix", "expected_limit"),
        [
            ("/celery/status", 10),  # 2s broker inspect per hit
            ("/", 60),  # static metadata
            ("/health", 120),  # highest legitimate LB poll volume
            ("/readyz", 60),  # DB + Redis round-trips per hit
            ("/metrics", 30),  # Prometheus scrapes 2–4/min
        ],
    )
    def test_root_probe_limits(self, path_suffix: str, expected_limit: int) -> None:
        app = _load_app()
        matches = [r for r in _all_api_routes(app) if r.path == path_suffix]
        assert len(matches) == 1, f"expected exactly one {path_suffix!r} route"
        deps = [d.dependency for d in matches[0].dependencies]
        assert deps, f"{path_suffix} lost its rate-limit dependency"
        cells = [v for func in deps for v in _closure_values(func)]
        assert expected_limit in cells, (
            f"{path_suffix} limit drifted from {expected_limit}: {cells}"
        )
        assert True in cells, f"{path_suffix} must be fail_open"

    @pytest.mark.parametrize(
        ("path_suffix", "expected_limit"),
        [
            ("/worker/health", 10),
            ("/db-health", 60),
            ("/redis-health", 60),
        ],
    )
    def test_simulation_probe_limits(self, path_suffix: str, expected_limit: int) -> None:
        app = _load_app()
        matches = _routes_ending_with(app, path_suffix)
        assert len(matches) == 1
        deps = [d.dependency for d in matches[0].dependencies]
        assert deps, f"{path_suffix} lost its rate-limit dependency"
        cells = [v for func in deps for v in _closure_values(func)]
        assert expected_limit in cells
        assert True in cells, f"{path_suffix} must be fail_open"

    def test_cluster_registry_is_limited_fail_closed(self) -> None:
        """The public cluster dump isn't availability-critical, so unlike
        the probes it uses the default fail-closed semantics."""
        app = _load_app()
        matches = _routes_ending_with(app, "/simulations/clusters")
        assert len(matches) == 1
        deps = [d.dependency for d in matches[0].dependencies]
        assert deps, "/clusters lost its rate-limit dependency"
        cells = [v for func in deps for v in _closure_values(func)]
        assert 30 in cells

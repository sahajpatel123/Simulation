"""Regression test for the rate limit on POST /simulations.

The simulation enqueue endpoint previously had no rate limit at the
IP+path level. A single actor could spam POSTs at the path, each
performing 3–4 DB queries (project lookup, env lookup, tier check,
quota UPDATE) before the quota 429 fires. The path could be used to
probe the DB or generate unhandled error volume.

The route now declares ``Depends(rate_limit(limit=30, window_s=60))``
so the IP+path bucket caps abuse well before the per-user monthly
quota is reached.

This is a source-grep test so we don't pull in the full module's
import chain (which depends on razorpay etc.).
"""

from __future__ import annotations

from pathlib import Path

_SIMULATIONS_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "api"
    / "v1"
    / "simulations.py"
)


def test_simulations_imports_rate_limiter() -> None:
    """The module must import rate_limit from app.core.rate_limiter."""
    source = _SIMULATIONS_PATH.read_text()
    assert "from app.core.rate_limiter import rate_limit" in source, (
        "simulations.py must import rate_limit so it can declare the "
        "IP+path limit on the enqueue endpoint."
    )


def test_create_simulation_declares_rate_limit_dependency() -> None:
    """The create_simulation route must declare a rate_limit dependency
    in its ``dependencies=[...]`` list — the global middleware does not
    cover it, so the route must opt in explicitly."""
    source = _SIMULATIONS_PATH.read_text()

    # Find the create_simulation route decorator block.
    import re

    route_block = re.search(
        r"@router\.post\([\s\S]*?def create_simulation\(",
        source,
    )
    assert route_block, "create_simulation route not found"
    block = route_block.group(0)

    assert "dependencies=[" in block, (
        "create_simulation must declare a ``dependencies=[...]`` list "
        "containing the rate_limit dep."
    )
    assert "rate_limit(" in block, (
        "create_simulation's dependencies must include a rate_limit() call."
    )


def test_rate_limit_value_is_reasonable() -> None:
    """The rate limit must be at least 1 (otherwise no legitimate
    traffic) and at most 120 (otherwise abuse-friendly). Choose 30/min
    as the documented default — adjust if changed intentionally."""
    source = _SIMULATIONS_PATH.read_text()

    import re
    match = re.search(r"rate_limit\(limit=(\d+),\s*window_s=(\d+)\)", source)
    assert match, "No rate_limit(limit=N, window_s=N) call found on create_simulation"
    limit, window = int(match.group(1)), int(match.group(2))
    assert 1 <= limit <= 120, f"rate_limit limit={limit} out of sane range"
    assert 1 <= window <= 600, f"rate_limit window_s={window} out of sane range"

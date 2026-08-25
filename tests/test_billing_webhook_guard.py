"""Pin the abuse-surface guards on the Razorpay webhook route.

The webhook is signature-verified but otherwise public, so it must carry
the fail-open rate limit — without a pin a refactor could silently drop
the dependency and leave the endpoint unbounded again.
"""

from __future__ import annotations

import pytest


def _dependency_closure_values(route) -> list:
    """Flatten every closure cell of every router-level dependency."""
    values: list = []
    for dep in route.dependencies:
        func = getattr(dep, "dependency", None)
        for cell in getattr(func, "__closure__", None) or ():
            try:
                values.append(cell.cell_contents)
            except ValueError:  # pragma: no cover - empty cell
                pass
    return values


def test_webhook_carries_generous_fail_open_rate_limit() -> None:
    pytest.importorskip("jwt")

    import sys
    import types

    razorpay_stub = types.ModuleType("razorpay")
    razorpay_stub.Client = object  # type: ignore[attr-defined]
    sys.modules.setdefault("razorpay", razorpay_stub)

    from app.api.v1 import billing as billing_mod

    webhooks = [r for r in billing_mod.router.routes if getattr(r, "path", "").endswith("/webhook")]
    assert len(webhooks) == 1
    route = webhooks[0]

    # The guard must exist...
    assert len(route.dependencies) >= 1
    # ...configured as designed: 120/min/IP sits far above real Razorpay
    # burst rates (backoff-driven retries) while making spam pointless,
    # and fail_open keeps payment state flowing if the limiter is down.
    cells = _dependency_closure_values(route)
    assert 120 in cells
    assert True in cells

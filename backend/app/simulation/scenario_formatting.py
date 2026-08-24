"""Pure presentation helpers shared by the what-if schema and engine.

Lives apart from ``app.simulation.what_if`` so that
``app.schemas.what_if`` can import these helpers at module level without
reaching into the engine — which in turn imports the schema types. That
schema ↔ engine pairing was the last static import cycle CodeQL flagged;
this module breaks it: both sides depend on here, and nothing here
depends on either.

No state, no I/O, no dependencies beyond the standard library.
"""

from __future__ import annotations

__all__ = ["direction_label", "format_delta_pct"]


def format_delta_pct(value: float, *, decimals: int = 2) -> str:
    """Format a percentage delta with a leading sign and fixed decimals.

    Example: ``format_delta_pct(12.34) == "+12.34%"``.
    Zero renders as ``"+0.00%"`` by design (matches the project convention
    used elsewhere in the what-if surface).
    """
    return f"{value:+.{decimals}f}%"


def direction_label(delta: float) -> str:
    """Return a human-readable direction label for ``delta``.

    Positive → "improvement", negative → "regression", otherwise "neutral".
    Uses the same 1e-9 tolerance as ``WhatIfOut.direction_arrow``.
    """
    if delta > 1e-9:
        return "improvement"
    if delta < -1e-9:
        return "regression"
    return "neutral"

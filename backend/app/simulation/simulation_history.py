"""Pure helpers for the lightweight simulation-history endpoint.

The route used to load every ``results_json`` row (potentially hundreds of
kilobytes per run for a 52-cluster simulation) just to read one or two
conversion-rate keys. This module holds the pure aggregation so the route
can instead issue a projected SQL read
(``results_json->>'population_weighted_conversion'``) and build the exact
same payload from tiny row dicts.

The helper is pure-Python (no SQL, no I/O). The route layer supplies rows
with ``conversion_rate`` already resolved, so the edge cases (empty table,
missing conversion rate, datetime serialisation) are testable without a
database.
"""
from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a value to float, returning ``default`` on bad data."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _direction(delta: float | None) -> str | None:
    if delta is None:
        return None
    if delta > 0:
        return "UP"
    if delta < 0:
        return "DOWN"
    return "FLAT"


def build_simulation_history(
    rows: list[dict[str, Any]] | None,
    *,
    project_id: int,
) -> dict[str, Any]:
    """Build the simulation-history payload from projected row dicts.

    Each row must contain at minimum ``id``, ``status``, ``created_at`` and
    ``conversion_rate`` (``signal_quality`` is optional). Rows are expected
    in ascending ``created_at`` order so ``delta_from_prev`` and
    ``direction`` match the previous run exactly as the legacy full-payload
    implementation did. ``conversion_rate`` may be a float or numeric text
    (the JSONB projection returns text); non-numeric values fall back to
    ``0.0`` instead of raising.
    """
    history: list[dict[str, Any]] = []
    prev_cr: float | None = None
    for row in rows or []:
        cr = round(_safe_float(row.get("conversion_rate")), 4)
        delta_cr = round(cr - prev_cr, 4) if prev_cr is not None else None
        created_at = row.get("created_at")
        created_at_str = (
            created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else created_at
        )
        history.append(
            {
                "simulation_id": int(row.get("id") or 0),
                "status": row.get("status"),
                "signal_quality": row.get("signal_quality"),
                "conversion_rate": cr,
                "delta_from_prev": delta_cr,
                "direction": _direction(delta_cr),
                "created_at": created_at_str,
            }
        )
        prev_cr = cr

    best_run_id = (
        max(history, key=lambda h: h["conversion_rate"])["simulation_id"]
        if history
        else None
    )
    return {
        "project_id": project_id,
        "total_runs": len(history),
        "history": history,
        "best_run_id": best_run_id,
    }


__all__ = ["build_simulation_history"]

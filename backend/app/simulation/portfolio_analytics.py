"""
Pure helpers for the user portfolio analytics rollup.

The route in ``app/api/v1/analytics.py`` (GET /analytics/me/portfolio)
issues a small handful of SQL queries, then hands the raw rows to these
helpers which compute aggregate statistics.

Keeping this layer pure means:

  1. No DB mocking required for tests — feed in dicts, assert on the dict
     output shape.
  2. The same rollup logic can be reused for portfolio exports or weekly
     digest emails without re-issuing SQL.
  3. Boundary cases (empty project, single simulation, zero outcomes)
     degrade to clean defaults rather than dividing-by-zero.
"""
from __future__ import annotations

import statistics
from typing import Any


def build_status_breakdown(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    """
    ``rows`` shape: ``[{"status": "DRAFT", "count": 3}, ...]``
    Returned shape::

        {"counts": {"DRAFT": 3, "COMPLETED": 2}, "total": 5}
    """
    counts: dict[str, int] = {}
    total = 0
    for row in rows or []:
        status = (row.get("status") or "UNKNOWN").upper()
        n = int(row.get("count") or 0)
        counts[status] = counts.get(status, 0) + n
        total += n
    # Stable ordering: by count desc, then name asc.
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return {"counts": ordered, "total": total}


def build_conversion_distribution(
    rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    ``rows`` shape: ``[{"conversion_rate": 0.05}, ...]`` — one per project
    (caller already pre-filters to "latest completed per project").

    Returns a ``ConversionDistribution``-shaped dict. Empty input → zero-count
    distribution with all stats ``None``.
    """
    rates: list[float] = []
    for row in rows or []:
        raw = row.get("conversion_rate")
        if raw is None:
            continue
        try:
            rates.append(float(raw))
        except (TypeError, ValueError):
            continue

    if not rates:
        return {
            "project_count": 0,
            "min": None,
            "median": None,
            "mean": None,
            "max": None,
        }

    return {
        "project_count": len(rates),
        "min": round(min(rates), 6),
        "median": round(statistics.median(rates), 6),
        "mean": round(statistics.fmean(rates), 6),
        "max": round(max(rates), 6),
    }


def build_failure_domain_counts(
    rows: list[dict[str, Any]] | None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    ``rows`` shape: ``[{"architect": "PricingArchitect", "count": 4}, ...]``

    Sorted by count desc, then name asc. Empty / unknown / None entries are
    filtered out so the dashboard only shows real architects.
    """
    cleaned: list[dict[str, Any]] = []
    for row in rows or []:
        name = row.get("architect")
        count = int(row.get("count") or 0)
        if not name or name.lower() in {"unknown", "null", "none"} or count <= 0:
            continue
        cleaned.append({"architect_name": str(name), "count": count})
    cleaned.sort(key=lambda r: (-r["count"], r["architect_name"]))
    return cleaned[: max(0, top_n)]


def build_stress_test_coverage(
    rows: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """
    ``rows`` shape: ``[{"stress_test_json": {...} | None}, ...]`` — one per
    project (caller already scopes to ``user_id``).

    Returns::

        {
          "total": 5,                          # total projects scanned
          "completed": 3,                      # status == COMPLETED
          "with_kill_shots": 1,                # kill_shots non-empty
          "with_partial_kill_shots": 2,        # partial_kill_shots non-empty
          "overall_risk_breakdown": {"LOW": 1, "HIGH": 1, "CRITICAL": 1},
        }
    """
    total = 0
    completed = 0
    with_kill_shots = 0
    with_partial = 0
    risk_counts: dict[str, int] = {}
    for row in rows or []:
        total += 1
        payload = row.get("stress_test_json") or row.get("data") or {}
        if not isinstance(payload, dict):
            continue
        if payload.get("status") == "COMPLETED":
            completed += 1
        if payload.get("kill_shots"):
            with_kill_shots += 1
        if payload.get("partial_kill_shots"):
            with_partial += 1
        risk = (payload.get("overall_risk_level") or "").upper()
        if risk:
            risk_counts[risk] = risk_counts.get(risk, 0) + 1

    return {
        "total": total,
        "completed": completed,
        "with_kill_shots": with_kill_shots,
        "with_partial_kill_shots": with_partial,
        "overall_risk_breakdown": dict(
            sorted(risk_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    }


def build_recent_projects(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """
    ``rows`` shape: each row already carries the fields needed for the
    dashboard. We just project + serialise.
    """
    out: list[dict[str, Any]] = []
    for row in rows or []:
        out.append(
            {
                "id": int(row.get("id") or 0),
                "title": str(row.get("title") or ""),
                "status": str(row.get("status") or "UNKNOWN").upper(),
                "updated_at": (
                    row.get("updated_at").isoformat()
                    if row.get("updated_at") is not None
                    and hasattr(row.get("updated_at"), "isoformat")
                    else row.get("updated_at")
                ),
                "has_completed_simulation": bool(row.get("has_completed_simulation")),
                "latest_conversion_rate": (
                    float(row["latest_conversion_rate"])
                    if row.get("latest_conversion_rate") is not None
                    else None
                ),
                "primary_failure_domain": row.get("primary_failure_domain"),
            }
        )
    return out


__all__ = [
    "build_status_breakdown",
    "build_conversion_distribution",
    "build_failure_domain_counts",
    "build_stress_test_coverage",
    "build_recent_projects",
]

"""
Pure helpers for the project portfolio rollup endpoint.

The portfolio-summary endpoint already aggregates findings /
outcomes / clusters / architect-accuracy across a flat
batch of sims. The natural sibling for the dashboard's
"all my projects" view is a per-project rollup: which of my
projects has the most sims, the most recent activity, the
worst calibration, the highest critical-finding density.

The helper takes rows of
``(project_id, project_title, sim_id, created_at, predicted,
actual)`` and emits one rollup row per project, sorted by
simulation_count DESC then project_id ASC (stable).

Pure-Python (no SQL, no I/O) — the route layer JOINs
``simulations`` → ``projects`` → ``outcomes`` and aggregates
the rows before invoking.
"""
from __future__ import annotations

import math


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def build_project_portfolio_rollup(
    rows: list[tuple],
    *,
    confidence_threshold: float = 0.02,
) -> dict:
    """Build the per-project portfolio rollup.

    Args:
        rows: list of ``(project_id, project_title, sim_id,
            created_at, predicted, actual)`` tuples. Missing
            predicted / actual rows are still counted for the
            project but excluded from the conversion mean.
        confidence_threshold: |prediction − actual| above this
            is counted as a "miscalibrated" sim. Default 2pp.

    Returns:
        A dict matching :class:`ProjectPortfolioRollupOut`:

        * ``projects`` — list of per-project rollup rows
          sorted by ``simulation_count`` DESC then
          ``project_id`` ASC. Each row carries
          ``project_id``, ``project_title``, ``simulation_count``,
          ``latest_sim_id``, ``latest_sim_created_at``,
          ``mean_predicted_conversion``,
          ``mean_actual_conversion``,
          ``miscalibrated_sim_count``.
        * ``total_projects`` — unique project count.
        * ``total_simulations`` — sum of simulation_count.
    """
    # Aggregate per project.
    per_project: dict[int, dict] = {}
    for (
        project_id,
        project_title,
        sim_id,
        created_at,
        predicted,
        actual,
    ) in rows:
        if project_id is None:
            continue
        slot = per_project.setdefault(
            int(project_id),
            {
                "project_id": int(project_id),
                "project_title": str(project_title or ""),
                "simulation_count": 0,
                "latest_sim_id": None,
                "latest_sim_created_at": None,
                "_preds": [],
                "_acts": [],
                "miscalibrated_sim_count": 0,
            },
        )
        slot["simulation_count"] += 1
        if sim_id is not None:
            slot["latest_sim_id"] = (
                int(sim_id) if slot["latest_sim_id"] is None
                else max(slot["latest_sim_id"], int(sim_id))
            )
        if created_at is not None:
            slot["latest_sim_created_at"] = (
                created_at
                if slot["latest_sim_created_at"] is None
                else created_at
            )
        p = _safe_float(predicted)
        a = _safe_float(actual)
        if p is not None and a is not None:
            slot["_preds"].append(p)
            slot["_acts"].append(a)
            if abs(p - a) > confidence_threshold:
                slot["miscalibrated_sim_count"] += 1

    # Build the project rows.
    rows_out: list[dict] = []
    for pid, slot in per_project.items():
        preds = slot.pop("_preds")
        acts = slot.pop("_acts")
        mean_pred = sum(preds) / len(preds) if preds else None
        mean_act = sum(acts) / len(acts) if acts else None
        ts = slot["latest_sim_created_at"]
        ts_str = (
            ts.isoformat()
            if hasattr(ts, "isoformat")
            else ts
        )
        rows_out.append({
            "project_id": slot["project_id"],
            "project_title": slot["project_title"],
            "simulation_count": slot["simulation_count"],
            "latest_sim_id": slot["latest_sim_id"],
            "latest_sim_created_at": ts_str,
            "mean_predicted_conversion": (
                round(mean_pred, 6) if mean_pred is not None else None
            ),
            "mean_actual_conversion": (
                round(mean_act, 6) if mean_act is not None else None
            ),
            "miscalibrated_sim_count": slot["miscalibrated_sim_count"],
        })

    # Sort by sim count DESC, then project_id ASC.
    rows_out.sort(
        key=lambda r: (-r["simulation_count"], r["project_id"]),
    )

    total_simulations = sum(r["simulation_count"] for r in rows_out)
    return {
        "projects": rows_out,
        "total_projects": len(rows_out),
        "total_simulations": total_simulations,
    }


__all__ = [
    "build_project_portfolio_rollup",
]
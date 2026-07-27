"""Pure helpers for the per-project export endpoint.

Composes a single full-project bundle (brief, assumptions,
simulations, decisions, outcomes, premortem, interventions)
into a JSON-ready payload so founders can archive one
project or hand it to a co-founder.

The helper is pure-Python (no SQL, no I/O). The route
layer pulls all child rows and hands them to
:func:`build_project_export`.

Output shape
------------
::

    {
      "exported_at": "ISO timestamp",
      "project_meta": {...},
      "brief": {...},
      "assumptions": [...],
      "simulations": [...],
      "decisions": [...],
      "outcomes": [...],
      "premortem": {...},
      "interventions": {...},
    }
"""
from __future__ import annotations

from datetime import datetime, timezone


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _safe_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(
        value, bool,
    ):
        return float(value)
    return None


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return None


def build_project_export(
    project_row: dict,
    brief_dict: dict | None,
    assumption_dicts: list[dict] | None,
    simulation_dicts: list[dict] | None,
    decision_dicts: list[dict] | None,
    outcome_dicts: list[dict] | None,
    premortem_data: dict | None,
    interventions_data: dict | None,
) -> dict:
    """Compose the per-project full export bundle.

    Args:
        project_row: minimal dict for the project's
            Project row (``id``, ``title``, ``description``,
            ``status``, ``created_at``, ``updated_at``,
            ``intake_mode``, ``tier`` if present, etc.).
        brief_dict: optional brief fields
            (``positioning``, ``features``, ``hook``,
            ``completed_at``).
        assumption_dicts: list of assumption row dicts.
        simulation_dicts: list of simulation row dicts.
        decision_dicts: list of decision row dicts.
        outcome_dicts: list of outcome row dicts.
        premortem_data: value of project.premortem_json.
        interventions_data: value of
            project.interventions_json.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    exported_at = datetime.now(timezone.utc).isoformat()

    # ---- Project meta -----------------------------------------------
    project_meta = {}
    if isinstance(project_row, dict):
        project_meta = {
            "id": project_row.get("id"),
            "title": project_row.get("title"),
            "description": project_row.get("description"),
            "status": project_row.get("status"),
            "intake_mode": project_row.get("intake_mode"),
            "created_at": _iso(project_row.get("created_at")),
            "updated_at": _iso(project_row.get("updated_at")),
        }

    # ---- Brief -----------------------------------------------------
    brief_out: dict = {}
    if isinstance(brief_dict, dict):
        brief_out = {
            "positioning": brief_dict.get("positioning") or "",
            "features": brief_dict.get("features") or [],
            "hook": brief_dict.get("hook") or "",
            "completed_at": _iso(
                brief_dict.get("completed_at"),
            ),
        }

    # ---- Assumptions ------------------------------------------------
    assumptions_out = []
    for a in assumption_dicts or []:
        if not isinstance(a, dict):
            continue
        assumptions_out.append({
            "id": a.get("id"),
            "text": a.get("text"),
            "category": a.get("category"),
            "sensitivity": a.get("sensitivity"),
            "impact_score": _safe_float(a.get("impact_score")),
            "is_hidden": bool(a.get("is_hidden") or False),
            "created_at": _iso(a.get("created_at")),
        })

    # ---- Simulations ------------------------------------------------
    simulations_out = []
    for s in simulation_dicts or []:
        if not isinstance(s, dict):
            continue
        results = s.get("results_json") or {}
        if not isinstance(results, dict):
            results = {}
        simulations_out.append({
            "id": s.get("id"),
            "status": s.get("status"),
            "predicted_conversion_rate": _safe_float(
                s.get("predicted_conversion_rate"),
            ),
            "actual_conversion_rate": _safe_float(
                s.get("actual_conversion_rate"),
            ),
            "mean_conversion_rate": _safe_float(
                results.get("mean_conversion_rate")
                or results.get("conversion_rate"),
            ),
            "revenue_projection": _safe_float(
                results.get("revenue_projection")
                or results.get("mean_revenue"),
            ),
            "confidence_score": _safe_float(
                s.get("confidence_score"),
            ),
            "created_at": _iso(s.get("created_at")),
        })

    # ---- Decisions --------------------------------------------------
    decisions_out = []
    for d in decision_dicts or []:
        if not isinstance(d, dict):
            continue
        decisions_out.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "created_at": _iso(d.get("created_at")),
        })

    # ---- Outcomes ---------------------------------------------------
    outcomes_out = []
    for o in outcome_dicts or []:
        if not isinstance(o, dict):
            continue
        outcomes_out.append({
            "id": o.get("id"),
            "actual_conversion_rate": _safe_float(
                o.get("actual_conversion_rate"),
            ),
            "actual_mrr": _safe_float(o.get("actual_mrr")),
            "calibration_score": _safe_float(
                o.get("calibration_score"),
            ),
            "created_at": _iso(o.get("created_at")),
        })

    return {
        "exported_at": exported_at,
        "schema_version": 1,
        "project_meta": project_meta,
        "brief": brief_out,
        "assumptions": assumptions_out,
        "simulations": simulations_out,
        "decisions": decisions_out,
        "outcomes": outcomes_out,
        "premortem": premortem_data or {},
        "interventions": interventions_data or {},
    }


__all__ = [
    "build_project_export",
]  # noqa: E501
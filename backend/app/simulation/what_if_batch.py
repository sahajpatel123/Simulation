"""
Pure batch what-if scenario comparison helpers.

Builds N ``WhatIfOut`` projections from one completed simulation and returns
them ranked by conversion delta with an aggregate ``WhatIfSummary``. No DB or
I/O — the route layer passes in the simulation's persisted results, the
environment params, and the project's existing assumptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.what_if import WhatIfOut, WhatIfSummary
from app.schemas.what_if_batch import (
    WhatIfBatchOut,
    WhatIfBatchScenarioOut,
)
from app.simulation.what_if import (
    build_what_if_scenario,
    summarise_what_if_scenarios,
)


def _assumption_dicts(assumptions: list[Any]) -> list[dict[str, Any]]:
    """Normalise ``WhatIfAssumption`` objects/dicts into the shape the builder expects."""
    out: list[dict[str, Any]] = []
    for item in assumptions or []:
        if hasattr(item, "model_dump"):
            out.append(item.model_dump())
        elif isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append(
                {
                    "text": str(getattr(item, "text", "")),
                    "sensitivity": str(getattr(item, "sensitivity", "MEDIUM")),
                    "impact_score": float(getattr(item, "impact_score", 5.0) or 5.0),
                }
            )
    return out


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json as _json

            parsed = _json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def build_what_if_batch(
    simulation_id: int,
    project_id: int,
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    scenarios: list[dict[str, Any]],
) -> WhatIfBatchOut:
    """Build and rank a batch of what-if scenario projections.

    ``scenarios`` is a list of dicts matching
    :class:`app.schemas.what_if_batch.WhatIfBatchScenarioInput`: each entry
    may carry ``label``, ``assumptions``, ``override_price_sensitivity``, and
    ``override_market_maturity``.
    """
    built: list[tuple[str, WhatIfOut]] = []
    for index, scenario_input in enumerate(scenarios or []):
        label = str(scenario_input.get("label") or "").strip()
        if not label:
            label = f"Scenario {index + 1}"
        out = build_what_if_scenario(
            simulation_id=simulation_id,
            project_id=project_id,
            base_results=_coerce_results(base_results),
            env_params=env_params,
            existing_assumptions=existing_assumptions,
            new_assumptions=_assumption_dicts(
                scenario_input.get("assumptions") or []
            ),
            override_price_sensitivity=scenario_input.get(
                "override_price_sensitivity"
            ),
            override_market_maturity=scenario_input.get(
                "override_market_maturity"
            ),
        )
        built.append((label, out))

    ordered = sorted(built, key=lambda pair: pair[1].conversion_delta, reverse=True)
    ranked_scenarios = [
        WhatIfBatchScenarioOut(
            rank=idx + 1,
            label=label,
            scenario=scenario,
        )
        for idx, (label, scenario) in enumerate(ordered)
    ]

    summary = summarise_what_if_scenarios([out for _, out in built])
    best_scenario = ranked_scenarios[0] if ranked_scenarios else None
    worst_scenario = ranked_scenarios[-1] if ranked_scenarios else None

    return WhatIfBatchOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status="COMPLETED",
        summary=summary,
        scenarios=ranked_scenarios,
        best_scenario=best_scenario,
        worst_scenario=worst_scenario,
        meta={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scenario_count": len(ranked_scenarios),
            "labels": [label for label, _ in built],
        },
    )


__all__ = ["build_what_if_batch"]

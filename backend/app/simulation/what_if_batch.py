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
    _safe_float,
    build_what_if_scenario,
    summarise_what_if_scenarios,
)


def _assumption_dicts(assumptions: list[Any]) -> list[dict[str, Any]]:
    """Normalise ``WhatIfAssumption`` objects/dicts into the shape the builder expects.

    Mirrors ``app.simulation.what_if._assumption_dicts`` but also accepts
    Pydantic models via ``model_dump()``. Sensitivity is uppercased so
    lowercase request payloads still match ``SENSITIVITY_WEIGHTS`` exactly.
    """
    out: list[dict[str, Any]] = []
    for item in assumptions or []:
        if isinstance(item, dict):
            out.append(
                {
                    "text": str(item.get("text", item.get("assumption", ""))),
                    "sensitivity": str(item.get("sensitivity", "MEDIUM")).upper(),
                    "impact_score": _safe_float(item.get("impact_score", 5.0), 5.0),
                }
            )
        elif hasattr(item, "model_dump"):
            dumped = item.model_dump()
            out.append(
                {
                    "text": str(dumped.get("text", "")),
                    "sensitivity": str(dumped.get("sensitivity", "MEDIUM")).upper(),
                    "impact_score": _safe_float(dumped.get("impact_score", 5.0), 5.0),
                }
            )
        elif hasattr(item, "text"):
            out.append(
                {
                    "text": str(item.text),
                    "sensitivity": str(getattr(item, "sensitivity", "MEDIUM")).upper(),
                    "impact_score": _safe_float(
                        getattr(item, "impact_score", 5.0), 5.0
                    ),
                }
            )
        else:
            out.append(
                {
                    "text": "",
                    "sensitivity": "MEDIUM",
                    "impact_score": 5.0,
                }
            )
    return out


def _scenario_dicts(scenarios: list[Any]) -> list[dict[str, Any]]:
    """Normalise ``WhatIfBatchScenarioInput`` models/dicts into plain dicts."""
    out: list[dict[str, Any]] = []
    for scenario in scenarios or []:
        if hasattr(scenario, "model_dump"):
            out.append(scenario.model_dump())
        elif isinstance(scenario, dict):
            out.append(dict(scenario))
        else:
            out.append(
                {
                    "label": str(getattr(scenario, "label", "")),
                    "assumptions": list(getattr(scenario, "assumptions", [])),
                    "override_price_sensitivity": getattr(
                        scenario, "override_price_sensitivity", None
                    ),
                    "override_market_maturity": getattr(
                        scenario, "override_market_maturity", None
                    ),
                }
            )
    return out


def build_what_if_batch(
    simulation_id: int,
    project_id: int,
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    scenarios: list[Any],
) -> WhatIfBatchOut:
    """Build and rank a batch of what-if scenario projections.

    ``scenarios`` is a list of ``WhatIfBatchScenarioInput`` models or plain
    dicts matching that schema: each entry may carry ``label``,
    ``assumptions``, ``override_price_sensitivity``, and
    ``override_market_maturity``.
    """
    built: list[tuple[str, WhatIfOut]] = []
    for index, scenario_input in enumerate(_scenario_dicts(scenarios)):
        label = str(scenario_input.get("label") or "").strip()
        if not label:
            label = f"Scenario {index + 1}"
        out = build_what_if_scenario(
            simulation_id=simulation_id,
            project_id=project_id,
            base_results=base_results,
            env_params=env_params,
            existing_assumptions=existing_assumptions,
            new_assumptions=_assumption_dicts(scenario_input.get("assumptions") or []),
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

"""
Pydantic schemas for the batch what-if scenario comparison endpoint
``POST /api/v1/simulations/{id}/what-if/batch``.

The batch endpoint lets a founder submit several what-if scenarios in one
call, reuses the same Markov projection as the single-scenario endpoint,
and returns a ranked comparison plus aggregate summary so the UI can show
"which change moves conversion the most" without N round-trips.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.what_if import WhatIfAssumption, WhatIfOut, WhatIfSummary


class WhatIfBatchScenarioInput(BaseModel):
    """One scenario in a batch what-if request."""

    label: str = Field(
        default="",
        max_length=80,
        description="Human-readable label shown in the ranked comparison",
    )
    assumptions: list[WhatIfAssumption] = Field(
        default_factory=list,
        max_length=20,
        description="Additional assumptions to apply on top of the simulation's existing assumptions",
    )
    override_price_sensitivity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override the environment's price_sensitivity (0.0-1.0)",
    )
    override_market_maturity: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override the environment's market_maturity (0.0-1.0)",
    )


class WhatIfBatchRequest(BaseModel):
    """Body for the batch what-if scenario comparison endpoint."""

    scenarios: list[WhatIfBatchScenarioInput] = Field(
        min_length=1,
        max_length=20,
        description="One to twenty scenarios to project and compare",
    )


class WhatIfBatchScenarioOut(BaseModel):
    """One ranked scenario in the batch comparison response."""

    rank: int = Field(default=1, ge=1)
    label: str = Field(default="")
    scenario: WhatIfOut


class WhatIfBatchOut(BaseModel):
    """Full ranked batch what-if comparison response."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    summary: WhatIfSummary
    scenarios: list[WhatIfBatchScenarioOut] = Field(default_factory=list)
    best_scenario: WhatIfBatchScenarioOut | None = None
    worst_scenario: WhatIfBatchScenarioOut | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "WhatIfBatchScenarioInput",
    "WhatIfBatchRequest",
    "WhatIfBatchScenarioOut",
    "WhatIfBatchOut",
]

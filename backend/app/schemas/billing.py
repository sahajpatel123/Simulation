from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Mirrors TIER_LIMITS keys in app/core/tier_enforcement.py — keep in sync.
VALID_PLANS = ("pro", "enterprise")


class CreateSubscriptionRequest(BaseModel):
    """Body for POST /billing/create-subscription.

    Replaces the prior ``body: dict`` so Pydantic enforces the plan
    enum and rejects unknown keys. The plan must be one of
    ``VALID_PLANS``; anything else raises 422 before any Razorpay
    call is attempted.
    """

    model_config = {"extra": "forbid"}

    plan: Literal["pro", "enterprise"] = "pro"


class HardwareCostAnalysisRequest(BaseModel):
    """Body for POST /hardware/{hw_id}/cost-analysis.

    Both fields are optional. ``target_price_inr`` overrides the
    product's stored price for the BOM estimate; ``moq`` is the
    minimum order quantity for the manufacturing estimate. Both are
    bounded so a hostile client cannot inject megabytes or values
    that would crash the cost calculator.
    """

    model_config = {"extra": "forbid"}

    target_price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    moq: int = Field(default=500, ge=1, le=10_000_000)


class HardwareTriggerConsumerSimRequest(BaseModel):
    """Body for POST /hardware/{hw_id}/consumer-simulation.

    Empty body is valid; the schema exists only to lock the contract
    and reject unknown keys at the validation layer.
    """

    model_config = {"extra": "forbid"}

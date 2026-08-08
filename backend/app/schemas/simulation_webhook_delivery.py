"""Pydantic schemas for webhook delivery history and retries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SimulationWebhookDeliveryOut(BaseModel):
    id: int
    webhook_subscription_id: int
    simulation_id: int | None = None
    event_type: str
    status: str
    attempt_status: str | None = None
    http_status: int | None = None
    error: str | None = None
    conversion_rate: float | None = None
    request_body: dict[str, Any] | None = None
    retry_count: int = 0
    delivered_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class SimulationWebhookDeliveryListOut(BaseModel):
    items: list[SimulationWebhookDeliveryOut] = Field(default_factory=list)


class SimulationWebhookRetryOut(BaseModel):
    delivery: SimulationWebhookDeliveryOut


__all__ = [
    "SimulationWebhookDeliveryOut",
    "SimulationWebhookDeliveryListOut",
    "SimulationWebhookRetryOut",
]

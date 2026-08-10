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


class SimulationWebhookBatchRetryOut(BaseModel):
    """Summary of a bulk retry over a webhook's failed delivery backlog.

    ``requested`` is the number of failed rows considered from the backlog;
    ``retried`` is how many new delivery attempts were actually made, and
    ``skipped`` counts rows that were not re-sent because they already had a
    later successful delivery or were deduplicated during this run.
    """

    requested: int
    retried: int
    skipped: int = 0
    succeeded: int
    failed: int
    failed_delivery_ids: list[int] = Field(default_factory=list)
    deliveries: list[SimulationWebhookDeliveryOut] = Field(default_factory=list)


class WebhookDeliveryErrorOut(BaseModel):
    error: str
    count: int


class SimulationWebhookDeliveryStatsOut(BaseModel):
    """Windowed health summary for one webhook subscription."""

    webhook_id: int
    window_days: int
    total_deliveries: int
    success_count: int
    failed_count: int
    success_rate: float | None = None
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    http_status_breakdown: dict[str, int] = Field(default_factory=dict)
    event_type_breakdown: dict[str, int] = Field(default_factory=dict)
    retry_count_total: int = 0
    max_retry_count: int = 0
    top_errors: list[WebhookDeliveryErrorOut] = Field(default_factory=list)
    first_delivery_at: datetime | None = None
    last_delivery_at: datetime | None = None
    last_delivery_status: str | None = None
    last_delivery_error: str | None = None
    health_label: str
    narrative: str


__all__ = [
    "SimulationWebhookDeliveryOut",
    "SimulationWebhookDeliveryListOut",
    "SimulationWebhookRetryOut",
    "SimulationWebhookBatchRetryOut",
    "SimulationWebhookDeliveryStatsOut",
    "WebhookDeliveryErrorOut",
]

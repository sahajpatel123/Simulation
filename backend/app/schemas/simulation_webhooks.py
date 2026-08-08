"""Pydantic schemas for simulation-completion webhook subscriptions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {"simulation.completed", "simulation.failed", "simulation.*"}
)
VALID_STATUSES: frozenset[str] = frozenset({"ACTIVE", "DISABLED"})


class SimulationWebhookCreate(BaseModel):
    url: str
    event_type: str = Field(default="simulation.completed")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        if not value.lower().startswith("https://"):
            raise ValueError("webhook url must be HTTPS")
        if len(value) > 2048:
            raise ValueError("webhook url is too long")
        return value

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in VALID_EVENT_TYPES:
            raise ValueError(
                "event_type must be one of simulation.completed, "
                "simulation.failed, or simulation.*"
            )
        return value


class SimulationWebhookUpdate(BaseModel):
    status: str = Field(default="ACTIVE")

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in VALID_STATUSES:
            raise ValueError("status must be ACTIVE or DISABLED")
        return value


class SimulationWebhookOut(BaseModel):
    id: int
    project_id: int
    url: str
    secret: str = ""
    status: str
    event_type: str
    last_delivery_at: datetime | None = None
    last_delivery_status: str | None = None
    last_delivery_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationWebhookListOut(BaseModel):
    items: list[SimulationWebhookOut] = Field(default_factory=list)


__all__ = [
    "SimulationWebhookCreate",
    "SimulationWebhookUpdate",
    "SimulationWebhookOut",
    "SimulationWebhookListOut",
]

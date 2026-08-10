"""Pydantic schemas for simulation-completion webhook subscriptions."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

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
        url = value.strip()
        if not url.lower().startswith("https://"):
            raise ValueError("webhook url must be HTTPS")
        if len(url) > 2048:
            raise ValueError("webhook url is too long")
        try:
            parsed = urlparse(url)
        except ValueError:
            raise ValueError("webhook url is invalid") from None
        if parsed.scheme.lower() != "https":
            raise ValueError("webhook url must be HTTPS")
        if not parsed.hostname:
            raise ValueError("webhook url must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("webhook url must not include credentials")
        return url

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
    """Partial update for a simulation webhook subscription.

    ``status`` keeps its existing default of ``ACTIVE`` so an empty or
    status-only body behaves exactly as before. ``url`` and ``event_type``
    are optional and only applied when explicitly provided, so a founder
    can retarget an existing subscription (staging URL to production, or
    narrow ``simulation.completed`` to ``simulation.*``) without deleting
    it, losing its delivery history, or rotating the signing secret.
    """

    status: str = Field(default="ACTIVE")
    url: str | None = None
    event_type: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in VALID_STATUSES:
            raise ValueError("status must be ACTIVE or DISABLED")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = value.strip()
        if not url.lower().startswith("https://"):
            raise ValueError("webhook url must be HTTPS")
        if len(url) > 2048:
            raise ValueError("webhook url is too long")
        try:
            parsed = urlparse(url)
        except ValueError:
            raise ValueError("webhook url is invalid") from None
        if parsed.scheme.lower() != "https":
            raise ValueError("webhook url must be HTTPS")
        if not parsed.hostname:
            raise ValueError("webhook url must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("webhook url must not include credentials")
        return url

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in VALID_EVENT_TYPES:
            raise ValueError(
                "event_type must be one of simulation.completed, "
                "simulation.failed, or simulation.*"
            )
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

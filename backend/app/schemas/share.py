"""
Pydantic schemas for the public share-token endpoints.

These power the read-only public link flow:

  * ``POST   /api/v1/simulations/{id}/share``  — owner mints a token
  * ``GET    /api/v1/share/{token}``           — anyone reads the result
  * ``GET    /api/v1/simulations/{id}/share``  — owner lists their tokens
  * ``DELETE /api/v1/simulations/{id}/share``  — owner revokes all

The token is opaque (URL-safe random) and only its SHA-256 hash is
persisted, so the public endpoint cannot be used to enumerate links
from a leaked DB row.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Owner-facing request / response
# ---------------------------------------------------------------------------


class ShareTokenCreateIn(BaseModel):
    """Body for ``POST /simulations/{id}/share`` — kept empty for now."""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class ShareTokenOut(BaseModel):
    """Response when the owner mints a new share token."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "5k8H2x3vQ1nP9rT4wY7zA0bC6dE8fG2hJ4kL6mN8pQ",
                "simulation_id": 42,
                "scope": "read_only",
                "expires_at": "2026-08-25T00:00:00Z",
                "created_at": "2026-07-26T00:00:00Z",
                "share_url": "/api/v1/share/5k8H2x3vQ1nP9rT4wY7zA0bC6dE8fG2hJ4kL6mN8pQ",
            }
        }
    )

    token: str = Field(
        ..., description="Plaintext token — returned ONCE on creation."
    )
    simulation_id: int
    scope: str = "read_only"
    expires_at: datetime
    created_at: datetime
    share_url: str = Field(
        ..., description="Absolute path the caller can share publicly."
    )


class ShareTokenListItem(BaseModel):
    """Owner-facing summary of a single share token (no plaintext)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 17,
                "simulation_id": 42,
                "scope": "read_only",
                "is_active": True,
                "created_at": "2026-07-26T00:00:00Z",
                "expires_at": "2026-08-25T00:00:00Z",
                "revoked_at": None,
                "last_accessed_at": "2026-07-27T15:42:11Z",
                "access_count": 12,
            }
        }
    )

    id: int
    simulation_id: int
    scope: str = "read_only"
    is_active: bool = Field(
        ...,
        description="True when not revoked and not expired.",
    )
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_accessed_at: datetime | None = None
    access_count: int = 0


class ShareTokenListOut(BaseModel):
    """List of tokens for a single simulation, owner-facing."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "simulation_id": 42,
                "active_count": 1,
                "revoked_count": 0,
                "expired_count": 0,
                "tokens": [
                    {
                        "id": 17,
                        "simulation_id": 42,
                        "scope": "read_only",
                        "is_active": True,
                        "created_at": "2026-07-26T00:00:00Z",
                        "expires_at": "2026-08-25T00:00:00Z",
                        "revoked_at": None,
                        "last_accessed_at": None,
                        "access_count": 0,
                    }
                ],
            }
        }
    )

    simulation_id: int
    active_count: int
    revoked_count: int
    expired_count: int
    tokens: list[ShareTokenListItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public-facing response (anonymized)
# ---------------------------------------------------------------------------


class SharedSimulationOut(BaseModel):
    """Anonymized simulation payload returned to anyone with the token."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_title": "Untitled Project",
                "product_type_detected": "saas",
                "status": "COMPLETED",
                "signal_quality": 0.74,
                "population_weighted_conversion": 0.062,
                "revenue_projection": 124000.0,
                "primary_failure_domain": "Pricing",
                "funnel": {
                    "ARRIVE": 10000,
                    "BROWSE": 8700,
                    "CONSIDER": 5394,
                    "DECIDE": 2481,
                    "PURCHASE": 769,
                },
                "domain_findings": [
                    {
                        "domain": "Pricing",
                        "severity": "CRITICAL",
                        "narrative": "AOV above cluster willingness-to-pay for 41% of agents.",
                    }
                ],
                "shared_at": "2026-07-26T00:00:00Z",
                "expires_at": "2026-08-25T00:00:00Z",
            }
        }
    )

    project_title: str
    product_type_detected: str | None = None
    status: str
    signal_quality: float | None = None
    population_weighted_conversion: float | None = None
    revenue_projection: float | None = None
    primary_failure_domain: str | None = None
    funnel: dict[str, Any] = Field(default_factory=dict)
    domain_findings: list[dict[str, Any]] = Field(default_factory=list)
    shared_at: datetime
    expires_at: datetime


__all__ = [
    "ShareTokenCreateIn",
    "ShareTokenOut",
    "ShareTokenListItem",
    "ShareTokenListOut",
    "SharedSimulationOut",
]

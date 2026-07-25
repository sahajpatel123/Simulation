"""
Pydantic schemas for the public share-token endpoints.

These power the read-only public link flow:

  * ``POST /api/v1/simulations/{id}/share``  — owner mints a token
  * ``GET  /api/v1/share/{token}``           — anyone reads the result
  * ``DELETE /api/v1/simulations/{id}/share`` — owner revokes

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
    "SharedSimulationOut",
]
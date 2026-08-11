"""Pydantic schemas for personal API-token management.

Long-lived bearer credentials let founders and CI systems call the API
without password / JWT refresh flows. Plaintext tokens are returned exactly
once at creation; list responses only expose metadata (hash, name, scope,
expiry, usage timestamps).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

API_TOKEN_SCOPE_READ: str = "read"
API_TOKEN_SCOPE_READ_WRITE: str = "read_write"
API_TOKEN_SCOPES: tuple[str, ...] = (
    API_TOKEN_SCOPE_READ,
    API_TOKEN_SCOPE_READ_WRITE,
)


class ApiTokenCreateIn(BaseModel):
    """Body for ``POST /users/me/api-tokens``."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable label, e.g. 'staging CI'.",
    )
    scope: Literal["read", "read_write"] = API_TOKEN_SCOPE_READ
    expires_in_days: int | None = Field(
        default=90,
        ge=1,
        le=365,
        description="Token lifetime in days (default 90, max 365).",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class ApiTokenOut(BaseModel):
    """Create response — the only time the plaintext token is returned."""

    id: int
    name: str
    token: str
    scope: str
    expires_at: datetime | None
    created_at: datetime


class ApiTokenListItem(BaseModel):
    """Owner-facing metadata for one API token (never the plaintext)."""

    id: int
    name: str
    scope: str
    is_active: bool
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiTokenListOut(BaseModel):
    """List response with an at-a-glance active count."""

    active_count: int = 0
    items: list[ApiTokenListItem] = Field(default_factory=list)


__all__ = [
    "API_TOKEN_SCOPE_READ",
    "API_TOKEN_SCOPE_READ_WRITE",
    "API_TOKEN_SCOPES",
    "ApiTokenCreateIn",
    "ApiTokenOut",
    "ApiTokenListItem",
    "ApiTokenListOut",
]

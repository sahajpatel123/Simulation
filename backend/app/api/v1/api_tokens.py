"""Personal API-token management endpoints.

Long-lived bearer credentials for programmatic access. Tokens are scoped
("read" blocks mutating methods, "read_write" allows the full surface),
expire by default after 90 days, and can be revoked individually. The
plaintext token is returned exactly once at creation; every other response
exposes only metadata so a list leak cannot be replayed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.security import (
    api_token_expiry,
    api_token_is_expired,
    generate_api_token,
    hash_api_token,
)
from app.models.api_token import ApiToken
from app.models.user import User
from app.schemas.api_token import (
    ApiTokenCreateIn,
    ApiTokenListItem,
    ApiTokenListOut,
    ApiTokenOut,
)

router = APIRouter(prefix="/users/me/api-tokens", tags=["users"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}

# Per-user cap on usable (not revoked / not expired) tokens. Enough for
# per-environment CI credentials while preventing quota abuse.
MAX_ACTIVE_TOKENS: int = 20


def _is_usable(row: ApiToken, now: datetime | None = None) -> bool:
    """Return whether a token row can still authenticate requests."""
    return row.revoked_at is None and not api_token_is_expired(row.expires_at, now)


def _get_owned_token(
    db: Session,
    user_id: int,
    token_id: int,
) -> ApiToken:
    row = (
        db.query(ApiToken)
        .filter(ApiToken.id == token_id, ApiToken.user_id == user_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="API token not found")
    return row


@router.post(
    "",
    response_model=ApiTokenOut,
    status_code=201,
    summary="Create a personal API token (plaintext returned once)",
    responses=_JSON_200,
    # Minting tokens is cheap but per-user state-changing; cap path spam so a
    # script cannot exhaust the active-token quota with repeated 400s.
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def create_api_token(
    payload: ApiTokenCreateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiTokenOut:
    """Issue a new scoped API token for the authenticated user."""
    now = datetime.now(UTC)
    active_rows = (
        db.query(ApiToken)
        .filter(
            ApiToken.user_id == current_user.id,
            ApiToken.revoked_at.is_(None),
        )
        .all()
    )
    active_count = sum(1 for row in active_rows if _is_usable(row, now))
    if active_count >= MAX_ACTIVE_TOKENS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Active API token limit reached ({MAX_ACTIVE_TOKENS}). "
                "Revoke an existing token before creating another."
            ),
        )

    plaintext = generate_api_token()
    row = ApiToken(
        user_id=current_user.id,
        name=payload.name,
        token_hash=hash_api_token(plaintext),
        scope=payload.scope,
        expires_at=api_token_expiry(payload.expires_in_days),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return ApiTokenOut(
        id=row.id,
        name=row.name,
        token=plaintext,
        scope=row.scope,
        expires_at=row.expires_at,
        created_at=row.created_at,
    )


@router.get(
    "",
    response_model=ApiTokenListOut,
    summary="List personal API tokens (metadata only, no plaintext)",
    responses=_JSON_200,
)
def list_api_tokens(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiTokenListOut:
    """Return all of the user's API tokens, newest first, without secrets."""
    rows = (
        db.query(ApiToken)
        .filter(ApiToken.user_id == current_user.id)
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        .all()
    )
    items = [
        ApiTokenListItem(
            id=row.id,
            name=row.name,
            scope=row.scope,
            is_active=_is_usable(row),
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]
    return ApiTokenListOut(
        active_count=sum(1 for item in items if item.is_active),
        items=items,
    )


@router.delete(
    "/{token_id}",
    summary="Revoke a personal API token",
    responses=_JSON_200,
)
def revoke_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, bool]:
    """Revoke a token so it immediately stops authenticating requests.

    Idempotent: revoking an already-revoked token is a no-op success.
    """
    row = _get_owned_token(db, current_user.id, token_id)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()
    return {"ok": True}


__all__ = [
    "router",
    "create_api_token",
    "list_api_tokens",
    "revoke_api_token",
]

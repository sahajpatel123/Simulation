from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    API_TOKEN_HASH_V2_PREFIX,
    API_TOKEN_PREFIX,
    api_token_hash_candidates,
    api_token_is_expired,
    decode_token,
    hash_api_token,
)
from app.models.api_token import ApiToken
from app.models.environment import Environment as EnvironmentModel
from app.models.user import User

security = HTTPBearer()

# Methods a "read"-scoped API token may call. Everything else (POST, PUT,
# PATCH, DELETE) requires an explicit "read_write" token.
_API_TOKEN_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
# Refresh the last-used timestamp at most once per hour per token so token
# usage stays observable without turning every request into a DB write.
_LAST_USED_REFRESH_SECONDS: float = 60.0 * 60.0


def user_from_access_sub(db: Session, sub: str) -> User | None:
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == uid).first()


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalise a possibly-naive datetime to UTC-aware for comparisons."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def lookup_api_token_row(db: Session, token: str) -> ApiToken | None:
    """Resolve a presented API token to its ``ApiToken`` row, upgrading legacy digests.

    Rows written before the v2 HMAC scheme hold a bare SHA-256 hex digest.
    When such a row still matches, it is rewritten in place to the current
    ``v2:`` form the first time its token is legitimately used, so the
    legacy fast-hash digest stops being accepted as soon as a stronger one
    can replace it. The write is fail-open — a failed upgrade must never
    block authentication; the next successful request retries it.
    """
    row = (
        db.query(ApiToken)
        .filter(ApiToken.token_hash.in_(api_token_hash_candidates(token)))
        .first()
    )
    if row is not None and not row.token_hash.startswith(API_TOKEN_HASH_V2_PREFIX):
        try:
            row.token_hash = hash_api_token(token)
            db.commit()
        except Exception:  # noqa: BLE001 - digest upgrades must never block auth
            db.rollback()
    return row


def user_from_api_token(
    db: Session,
    token: str,
    request: Request,
) -> User | None:
    """Resolve a personal API token to its user, or ``None`` when unusable.

    Only the SHA-256 hash is looked up; revoked and expired tokens fail
    closed, and a ``read``-scoped token cannot call mutating methods (that
    becomes a 403 so callers know to use ``read_write``). The ``last_used_at``
    stamp is refreshed on a throttled basis so the write cost stays bounded.
    """
    if not token.startswith(API_TOKEN_PREFIX):
        return None
    row = lookup_api_token_row(db, token)
    if row is None or row.revoked_at is not None:
        return None
    if api_token_is_expired(row.expires_at):
        return None

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        return None

    method = (request.method or "GET").upper()
    if row.scope != "read_write" and method not in _API_TOKEN_READ_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "API token scope 'read' cannot call "
                f"{method} {request.url.path}"
            ),
        )

    now = datetime.now(UTC)
    last_used = _as_utc(row.last_used_at)
    if last_used is None or (now - last_used).total_seconds() >= _LAST_USED_REFRESH_SECONDS:
        row.last_used_at = now
        try:
            db.commit()
        except Exception:  # noqa: BLE001 - usage stamping must never block auth
            db.rollback()
    return user


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    sub = decode_token(token, token_type="access")

    if not sub:
        api_user = user_from_api_token(db, token, request)
        if api_user is not None:
            return api_user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = user_from_access_sub(db, sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    """Resolve the current user from a JWT or personal API token.

    Returns ``None`` when no credentials are sent or the credentials are
    invalid / expired / revoked. A *valid* API token whose scope forbids
    the requested method is deliberately not downgraded to anonymous:
    ``user_from_api_token`` raises 403 and it propagates, so a read-scoped
    token can never silently pass as "no credential" on a mutating
    optional-auth endpoint.
    """
    if not credentials:
        return None
    token = credentials.credentials
    sub = decode_token(token, token_type="access")
    if sub:
        return user_from_access_sub(db, sub)
    try:
        return user_from_api_token(db, token, request)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise
        return None


def require_environment(
    project_id: int,
    db: Session,
) -> EnvironmentModel:
    env = (
        db.query(EnvironmentModel)
        .filter(EnvironmentModel.project_id == project_id)
        .first()
    )
    if not env:
        raise HTTPException(
            status_code=400,
            detail=(
                "Environment not configured. "
                "POST /api/v1/projects/{id}/environments before running simulation."
            ),
        )
    return env


def require_admin(current_user: User) -> None:
    """Raise 403 unless the user is an admin.

    Two paths to admin access:

    - ``current_user.is_admin`` set on the User row (DB flag — set by
      promotion, not exposed via the public API).
    - The user's email is in the comma-separated ``ADMIN_EMAILS`` env
      var (lowercased before comparison; comparison is case-
      insensitive so the env var doesn't have to match the stored
      email's casing).

    Centralised here so every admin endpoint resolves to the same
    rule — duplicating the check across analytics / calibration is a
    security smell because a future change to one copy won't reach
    the others.
    """
    if getattr(current_user, "is_admin", False):
        return
    if settings.ADMIN_EMAILS:
        allowed = {
            e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()
        }
        if current_user.email and current_user.email.lower() in allowed:
            return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

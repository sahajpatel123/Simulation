from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.environment import Environment as EnvironmentModel
from app.models.user import User

security = HTTPBearer()


def user_from_access_sub(db: Session, sub: str) -> User | None:
    try:
        uid = int(sub)
    except (TypeError, ValueError):
        return None
    return db.query(User).filter(User.id == uid).first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    sub = decode_token(token, token_type="access")

    if not sub:
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
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    sub = decode_token(credentials.credentials, token_type="access")
    if not sub:
        return None
    return user_from_access_sub(db, sub)


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

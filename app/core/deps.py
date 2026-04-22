from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token

# Re-export for routers that import get_db from deps.
__all__ = ("get_db", "get_current_user", "get_current_user_optional", "user_from_access_sub", "require_environment")
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

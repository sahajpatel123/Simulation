import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.rate_limiter import rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    AccountDelete,
    MessageResponse,
    PasswordChange,
    RefreshRequest,
    Token,
    UserCreate,
    UserLogin,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])

EXPIRES_IN_SECONDS = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _store_refresh_token(db: Session, user_id: int, raw_token: str) -> None:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db.execute(
        text(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at, revoked)
            VALUES (:uid, :hash, NOW() + INTERVAL '30 days', NOW(), FALSE)
            """
        ),
        {"uid": user_id, "hash": token_hash},
    )


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit(limit=5, window_s=60))],
)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        tier="free",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token()
    _store_refresh_token(db, user.id, refresh_token)
    db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=EXPIRES_IN_SECONDS,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/login",
    response_model=Token,
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token()
    _store_refresh_token(db, user.id, refresh_token)
    db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=EXPIRES_IN_SECONDS,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def refresh_access_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    raw_token = payload.refresh_token
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    row = db.execute(
        text(
            """
            SELECT user_id, expires_at, revoked
            FROM refresh_tokens
            WHERE token_hash = :hash
            """
        ),
        {"hash": token_hash},
    ).mappings().first()

    if not row:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    if row["revoked"]:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked"
        )
    exp = row["expires_at"]
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and datetime.now(timezone.utc) > exp:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired"
        )

    new_access = create_access_token(str(row["user_id"]))
    return AccessTokenResponse(
        access_token=new_access,
        token_type="bearer",
        expires_in=EXPIRES_IN_SECONDS,
    )


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update identity, preferences, or cast defaults on the authenticated user."""
    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"] and data["email"] != current_user.email:
        taken = (
            db.query(User)
            .filter(User.email == data["email"], User.id != current_user.id)
            .first()
        )
        if taken:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )

    if "default_reader_count" in data and data["default_reader_count"] is not None:
        rc = int(data["default_reader_count"])
        data["default_reader_count"] = max(1000, min(10000, rc))

    for field, value in data.items():
        setattr(current_user, field, value)

    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return MessageResponse(message="Password updated")


@router.delete("/me", response_model=MessageResponse)
def delete_me(
    payload: AccountDelete,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Permanently delete the authenticated account and every cascade-linked
    record (projects, assumptions, environments, simulations, outcomes…).
    """
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is incorrect",
        )
    db.delete(current_user)
    db.commit()
    return MessageResponse(message="Account deleted")


@router.post("/logout", response_model=MessageResponse)
def logout():
    return MessageResponse(message="Logged out successfully")

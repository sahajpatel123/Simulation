import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
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

# How recently a token may have been revoked before its replay counts as a
# breach signal rather than an innocent concurrent double-fire. Two
# simultaneous refresh requests with the same token resolve in milliseconds
# (one wins the atomic claim, the loser then sees revoked=TRUE); treating
# that loser as theft would log the user out everywhere on every double
# fire. A replayed token revoked longer than this window ago, however, is
# the classic stolen-credential signature — the legitimate owner rotated
# past it long ago, so only an attacker still holds it.
REFRESH_REUSE_GRACE_SECONDS = 60

# A real bcrypt digest of a throwaway secret. The unknown-email branch of
# ``login`` verifies against it so both failure paths burn one bcrypt round
# — otherwise "no such user" returns measurably faster than "wrong
# password" and response latency becomes an account-enumeration oracle.
_DUMMY_PASSWORD_HASH = get_password_hash("timing-equalizer-not-a-credential")


def _store_refresh_token(db: Session, user_id: int, raw_token: str) -> None:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db.execute(
        text(
            """
            INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at, revoked)
            VALUES (:uid, :hash, :expires_at, NOW(), FALSE)
            """
        ),
        {
            "uid": user_id,
            "hash": token_hash,
            "expires_at": datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        },
    )


def _revoke_user_refresh_tokens(db: Session, user_id: int) -> int:
    result = db.execute(
        text(
            """
            UPDATE refresh_tokens
            SET revoked = TRUE, revoked_at = NOW()
            WHERE user_id = :uid AND revoked = FALSE
            """
        ),
        {"uid": user_id},
    )
    return int(result.rowcount or 0)


@router.post(
    "/register",
    response_model=Token,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
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
    summary="Sign in with email and password",
    dependencies=[Depends(rate_limit(limit=10, window_s=60))],
)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if user is None:
        # Unknown email — burn the same bcrypt work as the wrong-password
        # branch below so timing can't separate registered addresses from
        # unregistered ones.
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(payload.password, user.hashed_password):
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
    summary="Refresh access token using a refresh token",
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def refresh_access_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    raw_token = payload.refresh_token
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Atomically claim the refresh token by revoking it in one UPDATE.
    # The WHERE clause pins it to NOT revoked — if a concurrent request
    # already rotated the token, this returns rowcount=0 and we reject
    # the request. The single statement also replaces the prior
    # read-then-write race where a valid token could be rotated twice
    # (e.g. when two requests fire simultaneously) and produce duplicate
    # access sessions.
    claim = (
        db.execute(
            text(
                """
            UPDATE refresh_tokens
            SET revoked = TRUE, revoked_at = NOW()
            WHERE token_hash = :hash
              AND revoked = FALSE
              AND (expires_at IS NULL OR expires_at > NOW())
            RETURNING user_id
            """
            ),
            {"hash": token_hash},
        )
        .mappings()
        .first()
    )

    if not claim:
        # Reuse detection: the atomic claim failed, so this token was never
        # issued, expired unused, or was already rotated. Only the third
        # case is a breach signal — replaying a credential the legitimate
        # owner surrendered long ago means it was copied, so revoke every
        # session for that user. Tokens revoked within the grace window are
        # excluded by the SQL (concurrent double-fires) and unknown or
        # merely-expired tokens match nothing (normal lifecycle, no
        # side effects). The response stays uniform either way.
        cutoff = datetime.now(UTC) - timedelta(seconds=REFRESH_REUSE_GRACE_SECONDS)
        breach = (
            db.execute(
                text(
                    """
                SELECT user_id FROM refresh_tokens
                WHERE token_hash = :hash
                  AND revoked = TRUE
                  AND revoked_at IS NOT NULL
                  AND revoked_at < :cutoff
                """
                ),
                {"hash": token_hash, "cutoff": cutoff},
            )
            .mappings()
            .first()
        )
        if breach:
            _revoke_user_refresh_tokens(db, int(breach["user_id"]))
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user_id = int(claim["user_id"])
    new_refresh = create_refresh_token()
    _store_refresh_token(db, user_id, new_refresh)
    db.commit()

    new_access = create_access_token(str(user_id))
    return AccessTokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=EXPIRES_IN_SECONDS,
    )


@router.get(
    "/me",
    response_model=UserOut,
    summary="Get the authenticated user profile",
)
def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserOut,
    summary="Update the authenticated user profile",
    # Profile update writes to the users row — cap path-spam at
    # 20/min/IP so a runaway script can't churn through writes.
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update identity, preferences, or cast defaults on the authenticated user."""
    data = payload.model_dump(exclude_unset=True)

    if "email" in data and data["email"] and data["email"] != current_user.email:
        taken = (
            db.query(User).filter(User.email == data["email"], User.id != current_user.id).first()
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


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password for the authenticated user",
    # Password change is gated by requiring the current password, but
    # the outer IP cap stops an attacker who has somehow obtained
    # the current password (e.g. shoulder-surfing) from racing the
    # rotation. 5/min/IP is generous for a manual password change.
    dependencies=[Depends(rate_limit(limit=5, window_s=60))],
)
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
    _revoke_user_refresh_tokens(db, current_user.id)
    db.commit()
    return MessageResponse(message="Password updated")


@router.delete(
    "/me",
    response_model=MessageResponse,
    summary="Delete the authenticated account (requires password)",
    # Destructive — wipes the user row + cascades every project,
    # simulation, outcome, and refresh token. Cap path-spam at
    # 5/min/IP so a runaway script can't drain the auth table.
    dependencies=[Depends(rate_limit(limit=5, window_s=60))],
)
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
    _revoke_user_refresh_tokens(db, current_user.id)
    db.delete(current_user)
    db.commit()
    return MessageResponse(message="Account deleted")


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Log out and revoke active refresh tokens",
    # Logout is per-user, not IP-spammable, but a compromised
    # script could otherwise spam logout + DB-log writes
    # unbounded. 30/min/IP keeps accidental log spam bounded.
    dependencies=[Depends(rate_limit(limit=30, window_s=60))],
)
def logout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    revoked = _revoke_user_refresh_tokens(db, current_user.id)
    db.commit()
    return MessageResponse(message=f"Logged out successfully ({revoked} sessions revoked)")

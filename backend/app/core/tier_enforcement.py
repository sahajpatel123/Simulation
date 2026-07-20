from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.user import User

TIER_LIMITS = {
    "free": {
        "simulations_per_month": 2,
        "hardware_access": False,
        "ui_simulation_access": False,
        "pdf_reports": False,
    },
    "pro": {
        "simulations_per_month": 20,
        "hardware_access": True,
        "ui_simulation_access": True,
        "pdf_reports": True,
    },
    "enterprise": {
        "simulations_per_month": 999,
        "hardware_access": True,
        "ui_simulation_access": True,
        "pdf_reports": True,
    },
}


def _as_utc(expires: datetime) -> datetime:
    if expires.tzinfo is None:
        return expires.replace(tzinfo=timezone.utc)
    return expires.astimezone(timezone.utc)


def get_user_tier(user, db: Session) -> str:
    """Returns current tier. Downgrades to free if subscription expired."""
    st = getattr(user, "subscription_tier", None) or getattr(user, "tier", "free")
    tier = (st or "free").lower()
    expires = getattr(user, "subscription_expires_at", None)
    if expires and tier != "free":
        if datetime.now(timezone.utc) > _as_utc(expires):
            db.execute(
                text("UPDATE users SET subscription_tier = 'free' WHERE id = :uid"),
                {"uid": user.id},
            )
            db.commit()
            return "free"
    return tier


def reset_monthly_usage_if_needed(user, db: Session) -> None:
    """Resets simulations_used_this_month if calendar month changed."""
    reset_at = getattr(user, "usage_reset_at", None)
    now = datetime.now(timezone.utc)
    if reset_at is not None and reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    if reset_at is None or (now.year, now.month) != (reset_at.year, reset_at.month):
        db.execute(
            text("""
            UPDATE users
            SET simulations_used_this_month = 0,
                usage_reset_at = :now
            WHERE id = :uid
            """),
            {"now": now, "uid": user.id},
        )
        db.commit()


def enforce_simulation_limit(user, db: Session) -> None:
    """
    Atomically reserve one simulation slot for this user.

    Raises 429 if the user is at or over their monthly limit. Uses a single
    conditional UPDATE that atomically checks `simulations_used_this_month < limit`,
    applies the monthly reset if the calendar month changed, and increments the
    counter — eliminating the read-then-write TOCTOU window that previously
    allowed two concurrent enqueue requests to both observe `used=1` and
    overspend a 2/month plan. Returns the new used count and tier limit so
    callers can include them in 429 detail messages.
    """
    reset_monthly_usage_if_needed(user, db)
    uid = user.id
    u = db.query(User).filter(User.id == uid).first()
    if u is None:
        raise HTTPException(429, "User not found for simulation limit check.")
    tier = get_user_tier(u, db)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    monthly_cap = int(limits["simulations_per_month"])

    # Atomic compare-and-increment: only succeeds when used < cap. The WHERE
    # filter is the lock — under READ COMMITTED + a conditional UPDATE, two
    # concurrent transactions cannot both observe used=cap-1 and both increment.
    result = db.execute(
        text(
            """
            UPDATE users
            SET simulations_used_this_month = COALESCE(simulations_used_this_month, 0) + 1
            WHERE id = :uid
              AND COALESCE(simulations_used_this_month, 0) < :cap
            RETURNING simulations_used_this_month
            """
        ),
        {"uid": uid, "cap": monthly_cap},
    )
    row = result.fetchone()
    db.commit()

    if row is None:
        # Refresh to surface the current used count in the 429 message.
        current = db.execute(
            text("SELECT COALESCE(simulations_used_this_month, 0) FROM users WHERE id = :uid"),
            {"uid": uid},
        ).scalar() or 0
        raise HTTPException(
            429,
            (
                f"Simulation limit reached ({current}/{monthly_cap} this month). "
                f"Upgrade to Pro for more simulations."
            ),
        )


def enforce_hardware_access(user, db: Session) -> None:
    """Raises 403 if user tier does not include hardware simulation."""
    tier = get_user_tier(user, db)
    if not TIER_LIMITS.get(tier, {}).get("hardware_access", False):
        raise HTTPException(
            403,
            (
                "Hardware simulation is a Pro feature. "
                "Upgrade to access physics tests and hardware consumer simulation."
            ),
        )


def enforce_pdf_access(user, db: Session) -> None:
    """Raises 403 if user tier does not include PDF reports."""
    tier = get_user_tier(user, db)
    if not TIER_LIMITS.get(tier, {}).get("pdf_reports", False):
        raise HTTPException(403, "PDF reports are a Pro feature. Upgrade to download full reports.")


def increment_simulation_count(user_id: int, db: Session) -> None:
    """Call after a simulation completes successfully."""
    db.execute(
        text("""
        UPDATE users
        SET simulations_used_this_month = COALESCE(simulations_used_this_month, 0) + 1
        WHERE id = :uid
        """),
        {"uid": user_id},
    )
    db.commit()

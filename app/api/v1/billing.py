from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import razorpay
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.tier_enforcement import TIER_LIMITS
from app.models.user import User

router = APIRouter(prefix="/billing", tags=["billing"])


def get_razorpay_client() -> razorpay.Client:
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
    )


def _plan_to_tier_map() -> dict[str, str]:
    m: dict[str, str] = {}
    if settings.RAZORPAY_PRO_PLAN_ID:
        m[settings.RAZORPAY_PRO_PLAN_ID] = "pro"
    if settings.RAZORPAY_ENTERPRISE_PLAN_ID:
        m[settings.RAZORPAY_ENTERPRISE_PLAN_ID] = "enterprise"
    return m


# ── POST: create subscription ──


@router.post("/create-subscription")
async def create_subscription(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Body: {plan: "pro" | "enterprise"}
    Creates a Razorpay subscription and returns
    subscription_id + razorpay_key for frontend checkout.
    """
    plan_key = (body.get("plan") or "pro").lower()
    if plan_key not in ("pro", "enterprise"):
        raise HTTPException(400, detail='plan must be "pro" or "enterprise"')
    if plan_key == "pro":
        plan_id = settings.RAZORPAY_PRO_PLAN_ID
    else:
        plan_id = settings.RAZORPAY_ENTERPRISE_PLAN_ID
    if not plan_id:
        key = "RAZORPAY_PRO_PLAN_ID" if plan_key == "pro" else "RAZORPAY_ENTERPRISE_PLAN_ID"
        raise HTTPException(400, detail=f"Plan ID not configured. Set {key} in .env")

    client = get_razorpay_client()

    existing_customer_id = db.execute(
        text("SELECT razorpay_customer_id FROM users WHERE id = :uid"),
        {"uid": current_user.id},
    ).scalar_one_or_none()

    if not existing_customer_id:
        display_name = (current_user.full_name or "TheCee User").strip() or "TheCee User"
        customer = client.customer.create(
            {
                "name": display_name,
                "email": current_user.email or "",
                "contact": getattr(current_user, "phone", None) or "",
            }
        )
        existing_customer_id = customer["id"]
        db.execute(
            text("UPDATE users SET razorpay_customer_id = :cid WHERE id = :uid"),
            {"cid": existing_customer_id, "uid": current_user.id},
        )
        db.commit()

    subscription = client.subscription.create(
        {
            "plan_id": plan_id,
            "customer_notify": 1,
            "quantity": 1,
            "total_count": 12,
            "customer_id": existing_customer_id,
        }
    )

    db.execute(
        text("UPDATE users SET razorpay_subscription_id = :sid WHERE id = :uid"),
        {"sid": subscription["id"], "uid": current_user.id},
    )
    db.commit()

    plan_data = subscription.get("plan_data") or {}
    item = plan_data.get("item") or {}
    amount = item.get("amount", 0)

    return {
        "subscription_id": subscription["id"],
        "razorpay_key": settings.RAZORPAY_KEY_ID,
        "plan": plan_key,
        "amount": amount,
        "currency": "INR",
    }


# ── POST: webhook handler ──


@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(None, alias="X-Razorpay-Signature"),
):
    """
    Handles Razorpay webhook events.
    Verifies signature before processing.
    Updates subscription_tier + subscription_expires_at.
    """
    body_bytes = await request.body()

    if not settings.RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(500, detail="Webhook secret not configured")

    expected_sig = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, x_razorpay_signature or ""):
        raise HTTPException(400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(400, detail="Invalid JSON body") from None

    event = payload.get("event", "")
    sub_payload = (payload.get("payload") or {}).get("subscription") or {}
    entity = sub_payload.get("entity") or {}

    subscription_id = entity.get("id")
    plan_id = entity.get("plan_id")
    plan_map = _plan_to_tier_map()
    tier = plan_map.get(plan_id, "pro") if plan_id else "pro"

    if not subscription_id:
        return {"status": "ignored", "reason": "no subscription entity"}

    now = datetime.now(timezone.utc)

    if event == "subscription.activated":
        expires_at = now + timedelta(days=30)
        db.execute(
            text("""
            UPDATE users
            SET subscription_tier = :tier,
                subscription_expires_at = :expires
            WHERE razorpay_subscription_id = :sid
            """),
            {"tier": tier, "expires": expires_at, "sid": subscription_id},
        )
        db.commit()

    elif event == "subscription.charged":
        expires_at = now + timedelta(days=32)
        db.execute(
            text("""
            UPDATE users
            SET subscription_tier = :tier,
                subscription_expires_at = :expires
            WHERE razorpay_subscription_id = :sid
            """),
            {"tier": tier, "expires": expires_at, "sid": subscription_id},
        )
        db.commit()

    elif event in ("subscription.cancelled", "subscription.expired"):
        db.execute(
            text("""
            UPDATE users
            SET subscription_tier = 'free',
                subscription_expires_at = NULL
            WHERE razorpay_subscription_id = :sid
            """),
            {"sid": subscription_id},
        )
        db.commit()

    elif event == "subscription.halted":
        grace_expires = now + timedelta(days=3)
        db.execute(
            text("UPDATE users SET subscription_expires_at = :expires WHERE razorpay_subscription_id = :sid"),
            {"expires": grace_expires, "sid": subscription_id},
        )
        db.commit()

    return {"status": "processed", "event": event}


# ── GET: subscription status ──


@router.get("/subscription-status")
async def get_subscription_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.execute(
        text(
            """
        SELECT subscription_tier, subscription_expires_at,
               razorpay_subscription_id, simulations_used_this_month,
               usage_reset_at
        FROM users WHERE id = :uid
        """
        ),
        {"uid": current_user.id},
    ).mappings().first()

    if not row:
        raise HTTPException(404, detail="User not found")

    tier = (row["subscription_tier"] or current_user.tier or "free").lower()
    if tier not in TIER_LIMITS:
        tier = "free"
    expires = row["subscription_expires_at"]
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    is_active = tier == "free" or (expires is not None and now < expires)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])

    return {
        "tier": tier,
        "is_active": is_active,
        "expires_at": expires.isoformat() if expires else None,
        "razorpay_subscription_id": row["razorpay_subscription_id"],
        "simulations_used": row["simulations_used_this_month"] or 0,
        "simulations_limit": limits["simulations_per_month"],
        "hardware_access": limits["hardware_access"],
        "pdf_access": limits["pdf_reports"],
        "razorpay_key": settings.RAZORPAY_KEY_ID,
    }


# ── POST: cancel subscription ──


@router.post("/cancel-subscription")
async def cancel_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.execute(
        text("SELECT razorpay_subscription_id FROM users WHERE id = :uid"),
        {"uid": current_user.id},
    ).mappings().first()
    if not row or not row["razorpay_subscription_id"]:
        raise HTTPException(400, detail="No active subscription found")

    client = get_razorpay_client()
    try:
        client.subscription.cancel(
            row["razorpay_subscription_id"],
            {"cancel_at_cycle_end": 1},
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Razorpay cancellation failed: {e!s}") from e

    return {
        "status": "cancellation_scheduled",
        "message": "Subscription will cancel at end of current billing period.",
    }

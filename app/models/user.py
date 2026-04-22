from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    tier: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    subscription_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    simulations_used_this_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usage_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ── Press Office: identity ──────────────────────────────
    handle: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Press Office: house preferences ─────────────────────
    reduced_motion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_notices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    weekly_brief: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_units: Mapped[str] = mapped_column(String(8), default="inr", nullable=False)

    # ── Press Office: cast defaults ─────────────────────────
    default_reader_count: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    default_scenario: Mapped[str] = mapped_column(String(32), default="base", nullable=False)
    default_aov: Mapped[float] = mapped_column(Float, default=1000.0, nullable=False)
    keep_past_results: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )

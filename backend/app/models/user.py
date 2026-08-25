from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style imports + fully qualified string annotations below: these
    # peer-model edges stay type-checker visible while carrying no
    # module-level ``from``-imports, so no cyclic-import pattern exists.
    import app.models.api_token
    import app.models.project


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

    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retention_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    projects: Mapped[list["app.models.project.Project"]] = relationship(  # noqa: UP037
        "Project", back_populates="user", cascade="all, delete-orphan"
    )
    api_tokens: Mapped[list["app.models.api_token.ApiToken"]] = relationship(  # noqa: UP037
        "ApiToken", back_populates="user", cascade="all, delete-orphan"
    )

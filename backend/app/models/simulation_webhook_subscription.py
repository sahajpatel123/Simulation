from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SimulationWebhookSubscription(Base, TimestampMixin):
    """A founder-registered HTTPS endpoint that receives simulation events.

    Deliveries are signed with a per-subscription HMAC-SHA256 secret so the
    receiver can verify the payload came from TheCee.
    """

    __tablename__ = "simulation_webhook_subscriptions"
    __table_args__ = (
        Index(
            "ix_sim_webhook_project_status",
            "project_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, default="simulation.completed")

    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)

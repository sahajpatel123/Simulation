from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SimulationWebhookDelivery(Base, TimestampMixin):
    """One recorded attempt to deliver a simulation webhook event.

    The subscription row intentionally keeps only the most recent delivery
    metadata for cheap list views; this table is the durable, per-attempt
    audit trail that also powers manual retries of failed deliveries.
    """

    __tablename__ = "simulation_webhook_deliveries"
    __table_args__ = (
        Index(
            "ix_sim_webhook_delivery_sub_id_created",
            "webhook_subscription_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_subscription_id: Mapped[int] = mapped_column(
        ForeignKey(
            "simulation_webhook_subscriptions.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    simulation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempt_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        doc=(
            "Simulation/ping status carried by the event (COMPLETED, FAILED, "
            "or PING). Stored so a manual retry can rebuild the original "
            "payload without inferring status from the event type."
        ),
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    request_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    subscription: Mapped["SimulationWebhookSubscription"] = relationship(
        "SimulationWebhookSubscription",
        back_populates="deliveries",
    )


__all__ = ["SimulationWebhookDelivery"]

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserMarketBlindspot(Base):
    __tablename__ = "user_market_blindspots"
    __table_args__ = (
        UniqueConstraint("user_id", "blindspot_type", "blindspot_value", name="uq_user_market_blindspots_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    blindspot_type: Mapped[str] = mapped_column(String(50), nullable=False)
    blindspot_value: Mapped[str] = mapped_column(String(200), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_surfaced_to_user: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

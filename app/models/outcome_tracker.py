from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OutcomeTracker(Base, TimestampMixin):
    __tablename__ = "outcome_tracker"
    __table_args__ = (Index("ix_outcome_tracker_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    simulation_id: Mapped[int | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"))
    actual_conversion_rate: Mapped[float | None] = mapped_column(Float)
    actual_revenue: Mapped[float | None] = mapped_column(Float)
    predicted_conversion_rate: Mapped[float | None] = mapped_column(Float)
    predicted_revenue: Mapped[float | None] = mapped_column(Float)
    variance: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped["Project"] = relationship("Project", back_populates="outcomes")

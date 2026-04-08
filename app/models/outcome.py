from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Outcome(Base, TimestampMixin):
    __tablename__ = "outcomes"
    __table_args__ = (Index("ix_outcomes_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    actual_conversion_rate: Mapped[float] = mapped_column(Float, nullable=False)
    actual_mrr: Mapped[float] = mapped_column(Float, nullable=False)
    actual_cac: Mapped[float] = mapped_column(Float, nullable=False)
    actual_churn_rate: Mapped[float] = mapped_column(Float, nullable=False)
    actual_dau: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_nps: Mapped[float | None] = mapped_column(Float, nullable=True)
    days_since_launch: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    predicted_conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    simulation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    variance_conversion: Mapped[float | None] = mapped_column(Float, nullable=True)
    variance_mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    variance_cac: Mapped[float | None] = mapped_column(Float, nullable=True)
    variance_churn: Mapped[float | None] = mapped_column(Float, nullable=True)

    calibration_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="outcomes")

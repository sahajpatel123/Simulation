from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style import + fully qualified string annotation below: this
    # peer-model edge stays type-checker visible while carrying no
    # module-level ``from``-import, so no cyclic-import pattern exists.
    import app.models.project


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

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    project: Mapped["app.models.project.Project"] = relationship(  # noqa: UP037
        "Project", back_populates="outcome_trackers"
    )

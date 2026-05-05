from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Simulation(Base, TimestampMixin):
    __tablename__ = "simulations"
    __table_args__ = (
        Index("ix_simulations_project_id", "project_id"),
        Index("ix_simulations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(String(50), default="QUEUED", nullable=False)
    consumer_volume: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    results_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    claim_confidence_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="simulations")
    environment: Mapped["Environment | None"] = relationship(
        "Environment", back_populates="simulations"
    )

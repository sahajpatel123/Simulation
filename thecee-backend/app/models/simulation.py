from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Simulation(Base, TimestampMixin):
    __tablename__ = "simulations"
    __table_args__ = (
        Index("ix_simulations_project_id", "project_id"),
        Index("ix_simulations_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment_id: Mapped[int | None] = mapped_column(ForeignKey("environments.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(50), default="QUEUED")
    consumer_volume: Mapped[int] = mapped_column(Integer, default=10000)
    results_json: Mapped[str | None] = mapped_column(Text)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped["Project"] = relationship("Project", back_populates="simulations")
    environment: Mapped["Environment | None"] = relationship("Environment", back_populates="simulations")
    consumer_agents: Mapped[list["ConsumerAgent"]] = relationship(
        "ConsumerAgent", back_populates="simulation", cascade="all, delete-orphan"
    )

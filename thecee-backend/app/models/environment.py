from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Environment(Base, TimestampMixin):
    __tablename__ = "environments"
    __table_args__ = (Index("ix_environments_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(50), default="MANUAL")
    consumer_volume: Mapped[int] = mapped_column(Integer, default=10000)
    growth_rate_per_month: Mapped[float | None] = mapped_column(Float)
    average_order_value: Mapped[float | None] = mapped_column(Float)
    manual_params_json: Mapped[str | None] = mapped_column(Text)
    scenario_type: Mapped[str | None] = mapped_column(String(100))

    project: Mapped["Project"] = relationship("Project", back_populates="environments")
    simulations: Mapped[list["Simulation"]] = relationship("Simulation", back_populates="environment")

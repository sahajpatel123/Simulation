from enum import Enum as PyEnum

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class EnvironmentMode(str, PyEnum):
    MANUAL = "MANUAL"
    SCENARIO = "SCENARIO"
    TREND = "TREND"


class ScenarioType(str, PyEnum):
    EARLY_ADOPTER = "EARLY_ADOPTER"
    SATURATED = "SATURATED"
    RECESSION = "RECESSION"
    HIGH_GROWTH = "HIGH_GROWTH"
    VIRAL_LAUNCH = "VIRAL_LAUNCH"


class Environment(Base, TimestampMixin):
    __tablename__ = "environments"
    __table_args__ = (Index("ix_environments_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    consumer_volume: Mapped[int] = mapped_column(Integer, default=10000)
    growth_rate_per_month: Mapped[float] = mapped_column(Float, default=5.0)
    average_order_value: Mapped[float] = mapped_column(Float, default=999.0)
    price_sensitivity: Mapped[float] = mapped_column(Float, default=0.5)
    market_maturity: Mapped[float] = mapped_column(Float, default=0.3)
    scenario_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manual_params_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trend_data_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="environment")
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="environment"
    )

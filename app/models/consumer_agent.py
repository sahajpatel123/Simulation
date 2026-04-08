from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ConsumerAgent(Base, TimestampMixin):
    __tablename__ = "consumer_agents"
    __table_args__ = (Index("ix_consumer_agents_simulation_id", "simulation_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False)
    demographic_json: Mapped[str | None] = mapped_column(Text)
    behavior_profile_json: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(50))
    funnel_stage_reached: Mapped[str | None] = mapped_column(String(50))
    price_sensitivity: Mapped[float | None] = mapped_column(Float)
    intent_level: Mapped[float | None] = mapped_column(Float)

    simulation: Mapped["Simulation"] = relationship("Simulation", back_populates="consumer_agents")

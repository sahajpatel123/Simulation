from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ClusterRunSummary(Base):
    """Per-cluster aggregate row for a simulation run (learning system)."""
    __tablename__ = "cluster_run_summaries"
    __table_args__ = (
        UniqueConstraint("simulation_id", "cluster_id", name="uq_cluster_run_summaries_sim_cluster"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(
        ForeignKey("simulations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cluster_id: Mapped[str] = mapped_column(String(100), nullable=False)
    agents_assigned: Mapped[int] = mapped_column(Integer, nullable=False)
    agents_converted: Mapped[int] = mapped_column(Integer, nullable=False)
    conversion_rate: Mapped[float] = mapped_column(Float, nullable=False)
    drop_state_distribution: Mapped[dict] = mapped_column(JSONB, nullable=False)
    mean_drop_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    architect_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    primary_drop_trigger: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signal_quality: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    claim_confidence_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

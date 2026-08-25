from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style imports + fully qualified string annotations below: these
    # peer-model edges stay type-checker visible while carrying no
    # module-level ``from``-imports, so no cyclic-import pattern exists.
    import app.models.environment
    import app.models.project


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
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    env_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    results_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    results_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    signal_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    claim_confidence_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    project: Mapped["app.models.project.Project"] = relationship(  # noqa: UP037
        "Project", back_populates="simulations"
    )
    environment: Mapped["app.models.environment.Environment | None"] = relationship(  # noqa: UP037
        "Environment", back_populates="simulations"
    )

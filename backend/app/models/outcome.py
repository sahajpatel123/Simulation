from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # codeql[py/unsafe-cyclic-import]: TYPE_CHECKING-guarded import — never executes at runtime, so no runtime cycle exists
    from app.models.project import Project


class Outcome(Base, TimestampMixin):
    __tablename__ = "outcomes"
    __table_args__ = (
        Index("ix_outcomes_project_id", "project_id"),
        # One client-supplied idempotency key per project. The partial
        # predicate lets callers retry outcome submissions safely (e.g.
        # after a network timeout) without ever creating duplicate rows:
        # NULL keys remain unconstrained, matching pre-existing rows.
        Index(
            "uq_outcomes_project_client_request",
            "project_id",
            "client_request_id",
            unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

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
    client_request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        doc=(
            "Optional caller-supplied idempotency key. When present, a "
            "repeated submission with the same key for the same project "
            "returns the original outcome instead of creating a duplicate."
        ),
    )

    project: Mapped[Project] = relationship("Project", back_populates="outcomes")

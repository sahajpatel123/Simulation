"""Persisted A/B landing-page experiments logged by founders.

The stateless ``POST /api/v1/experiments/ab-analysis`` endpoint returns a
statistical verdict for two observed arms, but does not remember the test.
This model gives each project a durable experiment registry: the raw
observed counts, statistical parameters, and the computed verdict snapshot
so founders can revisit tests, correct mis-logged numbers, and track their
landing-page experiment history over time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style import + fully qualified string annotation below: this
    # peer-model edge stays type-checker visible while carrying no
    # module-level ``from``-import, so no cyclic-import pattern exists.
    import app.models.project


class AbTestExperiment(Base, TimestampMixin):
    __tablename__ = "ab_test_experiments"
    __table_args__ = (
        Index("ix_ab_test_experiments_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)

    variant_a_label: Mapped[str] = mapped_column(String(80), nullable=False)
    variant_b_label: Mapped[str] = mapped_column(String(80), nullable=False)
    visitors_a: Mapped[int] = mapped_column(Integer, nullable=False)
    conversions_a: Mapped[int] = mapped_column(Integer, nullable=False)
    visitors_b: Mapped[int] = mapped_column(Integer, nullable=False)
    conversions_b: Mapped[int] = mapped_column(Integer, nullable=False)

    alpha: Mapped[float] = mapped_column(Float, nullable=False)
    power: Mapped[float] = mapped_column(Float, nullable=False)
    mde: Mapped[float] = mapped_column(Float, nullable=False)

    # Verdict snapshot — denormalised from analysis_json so list/dashboard
    # queries never need to re-run the statistics or re-parse the blob.
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False)
    winner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    absolute_uplift: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_uplift_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    p_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Full :class:`AbTestAnalysisOut` payload as computed when the counts
    # were last saved, so API responses stay byte-stable.
    analysis_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    project: Mapped["app.models.project.Project"] = relationship(  # noqa: UP037
        "Project",
        back_populates="ab_test_experiments",
    )

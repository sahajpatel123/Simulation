"""Persisted evidence rows for validation experiments run by founders.

Each row records the outcome of one experiment (method + result) attached
to a single assumption. The de-risking scorecard engine
(``app.simulation.evidence_scorecard``) turns these rows into confidence
upgrades/downgrades that feed back into the validation-ROI pipeline, so a
founder who actually runs the planned experiments sees the assumption move
from "validate first" to "de-risked" (or "challenged").
"""

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AssumptionEvidence(Base, TimestampMixin):
    __tablename__ = "assumption_evidence"
    __table_args__ = (
        Index(
            "ix_assumption_evidence_project_assumption",
            "project_id",
            "assumption_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    assumption_id: Mapped[int] = mapped_column(
        ForeignKey("assumptions.id", ondelete="CASCADE"), nullable=False
    )
    # One of METHOD_ID_LITERAL values from app.schemas.validation_experiment.
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    # PASS | FAIL | INCONCLUSIVE
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

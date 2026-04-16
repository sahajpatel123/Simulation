from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.decision import Decision
    from app.models.environment import Environment
    from app.models.outcome import Outcome
    from app.models.outcome_tracker import OutcomeTracker


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_user_id", "user_id"),
        Index("ix_projects_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    prototype_html: Mapped[str | None] = mapped_column(Text)
    funnel_graph_json: Mapped[str | None] = mapped_column(Text)
    premortem_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stress_test_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    interventions_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    competitive_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="projects")
    assumptions: Mapped[list["Assumption"]] = relationship(
        "Assumption", back_populates="project", cascade="all, delete-orphan"
    )
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="project", cascade="all, delete-orphan"
    )
    environment: Mapped["Environment | None"] = relationship(
        "Environment",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Decision.created_at.desc()",
    )
    outcomes: Mapped[list["Outcome"]] = relationship(
        "Outcome",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="Outcome.created_at.desc()",
    )
    outcome_trackers: Mapped[list["OutcomeTracker"]] = relationship(
        "OutcomeTracker",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="OutcomeTracker.recorded_at.desc()",
    )

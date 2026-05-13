from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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
    precis: Mapped[str | None] = mapped_column(Text, nullable=True)
    readings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last dossier title we used to mint ``precis`` (lazy backfill + rename detection).
    precis_title_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT")
    intake_mode: Mapped[str] = mapped_column(String(20), default="IDEA", nullable=False)
    landing_page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    mvp_feature_list: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    existing_product_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # software | hardware — NULL = legacy dossier (show both workshop paths in UI)
    dossier_axis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="FALSE")
    prototype_html: Mapped[str | None] = mapped_column(Text)
    funnel_graph_json: Mapped[str | None] = mapped_column(Text)
    premortem_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stress_test_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    interventions_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    competitive_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    brief_positioning: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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

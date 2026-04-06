from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


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

    user: Mapped["User"] = relationship("User", back_populates="projects")
    assumptions: Mapped[list["Assumption"]] = relationship(
        "Assumption", back_populates="project", cascade="all, delete-orphan"
    )
    simulations: Mapped[list["Simulation"]] = relationship(
        "Simulation", back_populates="project", cascade="all, delete-orphan"
    )
    environments: Mapped[list["Environment"]] = relationship(
        "Environment", back_populates="project", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        "Decision", back_populates="project", cascade="all, delete-orphan"
    )
    outcomes: Mapped[list["OutcomeTracker"]] = relationship(
        "OutcomeTracker", back_populates="project", cascade="all, delete-orphan"
    )

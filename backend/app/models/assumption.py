from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style import + fully qualified string annotation below: this
    # peer-model edge stays type-checker visible while carrying no
    # module-level ``from``-import, so no cyclic-import pattern exists.
    import app.models.project


class Assumption(Base, TimestampMixin):
    __tablename__ = "assumptions"
    __table_args__ = (Index("ix_assumptions_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    sensitivity: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    impact_score: Mapped[float] = mapped_column(Float, default=5.0)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    project: Mapped["app.models.project.Project"] = relationship(  # noqa: UP037
        "Project", back_populates="assumptions"
    )

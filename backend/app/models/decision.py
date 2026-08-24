from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    # Module-style import + fully qualified string annotation below: this
    # peer-model edge stays type-checker visible while carrying no
    # module-level ``from``-import, so no cyclic-import pattern exists.
    import app.models.project


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_project_id", "project_id"),
        Index("ix_decisions_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    results_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quoted despite future-annotations: unquoted dotted paths are
    # module-level attribute uses that re-trigger the cyclic-import pattern
    # this file layout exists to avoid.
    project: Mapped["app.models.project.Project"] = relationship(  # noqa: UP037
        "Project", back_populates="decisions"
    )

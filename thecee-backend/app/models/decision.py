from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    probability_distribution_json: Mapped[str | None] = mapped_column(Text)
    interventions_json: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship("Project", back_populates="decisions")

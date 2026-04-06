from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


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

    project: Mapped["Project"] = relationship("Project", back_populates="assumptions")

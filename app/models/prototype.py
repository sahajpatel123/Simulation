from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Prototype(Base, TimestampMixin):
    __tablename__ = "prototypes"
    __table_args__ = (Index("ix_prototypes_project_id", "project_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    html_content: Mapped[str | None] = mapped_column(Text)
    funnel_graph_json: Mapped[str | None] = mapped_column(Text)

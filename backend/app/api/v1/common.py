from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.project import Project


def get_owned_project(db: Session, user_id: int, project_id: int) -> Project:
    """Fetch a project by ID and verify ownership. Raises 404 if not found."""
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

import json

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.prompts import ASSUMPTION_EXTRACTION_PROMPT
from app.models.assumption import Assumption
from app.models.project import Project
from app.models.user import User
from app.schemas.assumption import (
    AssumptionExtractRequest,
    AssumptionListResponse,
    AssumptionOut,
)
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])

claude = Anthropic(api_key=settings.ANTHROPIC_API_KEY)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        status="DRAFT",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("", response_model=ProjectListResponse)
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .all()
    )
    return ProjectListResponse(
        projects=[ProjectOut.model_validate(p) for p in projects],
        total=len(projects),
    )


@router.get("/{project_id}/assumptions", response_model=AssumptionListResponse)
def get_assumptions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )
    hidden_count = sum(1 for a in assumptions if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in assumptions],
        total=len(assumptions),
        hidden_count=hidden_count,
    )


@router.post("/{project_id}/extract-assumptions", response_model=AssumptionListResponse)
def extract_assumptions(
    project_id: int,
    payload: AssumptionExtractRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    description = (
        payload.description
        if payload and payload.description
        else project.description
    )

    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Description too short to extract meaningful assumptions",
        )

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=(
                "You are a world-class startup mentor specializing in surfacing "
                "dangerous hidden assumptions that kill products. "
                "You ALWAYS return valid JSON only, no markdown, no explanation."
            ),
            messages=[
                {
                    "role": "user",
                    "content": ASSUMPTION_EXTRACTION_PROMPT.format(
                        description=description
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        parsed = json.loads(raw)
        assumptions_data = parsed.get("assumptions", [])

        if not isinstance(assumptions_data, list):
            raise ValueError("Claude returned unexpected format")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned invalid JSON — retry the request",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Assumption extraction failed: {str(e)}",
        )

    db.query(Assumption).filter(Assumption.project_id == project_id).delete()
    db.commit()

    saved = []
    for item in assumptions_data:
        sensitivity = str(item.get("sensitivity", "MEDIUM")).upper()
        if sensitivity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            sensitivity = "MEDIUM"

        assumption = Assumption(
            project_id=project_id,
            text=str(item.get("text", "")).strip(),
            category=str(item.get("category", "Market")).strip(),
            sensitivity=sensitivity,
            impact_score=min(10.0, max(1.0, float(item.get("impact_score", 5.0)))),
            is_hidden=bool(item.get("is_hidden", False)),
        )
        db.add(assumption)
        saved.append(assumption)

    project.status = "ASSUMPTIONS_EXTRACTED"
    db.commit()

    for assumption in saved:
        db.refresh(assumption)

    hidden_count = sum(1 for a in saved if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in saved],
        total=len(saved),
        hidden_count=hidden_count,
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut.model_validate(project)

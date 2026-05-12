from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.api.v1.common import get_owned_project
from app.models.assumption import Assumption
from app.models.decision import Decision
from app.models.outcome import Outcome
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.reports.generator import ReportGenerator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["reports"])

_PDF_200 = {200: {"description": "PDF report", "content": {"application/pdf": {}}}}
_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}


def _safe_filename(title: str) -> str:
    clean = "".join(char if char.isalnum() or char in (" ", "-", "_") else "_" for char in title)
    return clean.strip()[:40] or "project"


@router.post(
    "/{project_id}/report",
    summary="Generate a PDF dossier report for a project",
    responses=_PDF_200,
)
def generate_report(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .order_by(Simulation.created_at.desc())
        .first()
    )
    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )
    outcomes = (
        db.query(Outcome)
        .filter(Outcome.project_id == project_id)
        .order_by(Outcome.created_at.desc())
        .limit(10)
        .all()
    )
    latest_decision = (
        db.query(Decision)
        .filter(Decision.project_id == project_id, Decision.status == "COMPLETED")
        .order_by(Decision.created_at.desc())
        .first()
    )

    report_data = {
        "title": project.title or "Untitled Project",
        "description": project.description or "",
        "simulation": latest_sim.results_json if latest_sim else {},
        "assumptions": [
            {
                "text": assumption.text,
                "sensitivity": assumption.sensitivity,
                "impact_score": assumption.impact_score,
                "category": assumption.category,
            }
            for assumption in assumptions
        ],
        "premortem": getattr(project, "premortem_json", None),
        "stress_test": getattr(project, "stress_test_json", None),
        "interventions": getattr(project, "interventions_json", None),
        "competitive": getattr(project, "competitive_json", None),
        "decision": latest_decision.results_json if latest_decision else {},
        "outcomes": [
            {
                "actual_conversion_rate": outcome.actual_conversion_rate,
                "predicted_conversion_rate": outcome.predicted_conversion_rate,
                "variance": {"conversion": outcome.variance_conversion, "mrr": outcome.variance_mrr},
                "calibration_score": outcome.calibration_score,
                "recorded_at": outcome.created_at.isoformat() if outcome.created_at else "",
            }
            for outcome in outcomes
        ],
    }

    logger.info(
        "[Report] Generating PDF — project_id=%s has_sim=%s assumptions=%s outcomes=%s",
        project_id,
        latest_sim is not None,
        len(assumptions),
        len(outcomes),
    )

    try:
        generator = ReportGenerator()
        pdf_bytes = generator.generate(report_data)
    except Exception as exc:
        logger.exception("[Report] PDF generation failed — project_id=%s", project_id)
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(exc)}")

    filename = f"TheCee_Report_{_safe_filename(project.title or 'project')}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get(
    "/{project_id}/report/preview",
    summary="Report section checklist and recommended action",
    responses=_JSON_200,
)
def report_preview_metadata(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = get_owned_project(db, current_user.id, project_id)

    sim_count = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id, Simulation.status == "COMPLETED")
        .count()
    )
    assumption_count = db.query(Assumption).filter(Assumption.project_id == project_id).count()
    outcome_count = db.query(Outcome).filter(Outcome.project_id == project_id).count()

    return {
        "project_id": project_id,
        "title": project.title,
        "sections": {
            "executive_summary": sim_count > 0,
            "assumptions": assumption_count > 0,
            "funnel_analysis": sim_count > 0,
            "premortem": bool(getattr(project, "premortem_json", None)),
            "stress_test": bool(getattr(project, "stress_test_json", None)),
            "interventions": bool(getattr(project, "interventions_json", None)),
            "competitive": bool(getattr(project, "competitive_json", None)),
            "decision": (
                db.query(Decision)
                .filter(Decision.project_id == project_id, Decision.status == "COMPLETED")
                .count()
                > 0
            ),
            "outcomes": outcome_count > 0,
        },
        "simulation_runs": sim_count,
        "assumptions_count": assumption_count,
        "outcomes_count": outcome_count,
        "recommended_action": "Ready to generate" if sim_count > 0 else "Run a simulation first for a complete report",
    }

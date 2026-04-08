from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.models.environment import Environment
from app.models.project import Project
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.simulation import (
    SimulationCreate,
    SimulationOut,
    SimulationResultOut,
    SimulationStatusOut,
)
from app.tasks.simulation_tasks import health_check, run_full_simulation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.post("", response_model=SimulationStatusOut, status_code=status.HTTP_201_CREATED)
def create_simulation(
    payload: SimulationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    environment = (
        db.query(Environment)
        .filter(Environment.project_id == payload.project_id)
        .first()
    )
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /api/v1/projects/{id}/environments first.",
        )

    running = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == payload.project_id,
            Simulation.status.in_(["QUEUED", "RUNNING"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Simulation {running.id} is already {running.status} for this project.",
        )

    sim = Simulation(
        project_id=payload.project_id,
        environment_id=environment.id,
        status="QUEUED",
        consumer_volume=payload.consumer_volume,
    )
    db.add(sim)
    db.commit()
    db.refresh(sim)

    task = run_full_simulation.delay(sim.id)
    sim.task_id = task.id
    db.commit()
    db.refresh(sim)

    logger.info(f"[API] Simulation enqueued - simulation_id={sim.id} task_id={task.id}")

    return SimulationStatusOut.model_validate(sim)


@router.get("/worker/health")
def worker_health():
    try:
        result = health_check.delay()
        resp = result.get(timeout=5)
        return {"worker_reachable": True, "response": resp}
    except Exception as exc:
        return {"worker_reachable": False, "error": str(exc)}


@router.get("/{simulation_id}/status", response_model=SimulationStatusOut)
def get_simulation_status(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)
    return SimulationStatusOut.model_validate(sim)


@router.get("/{simulation_id}/results", response_model=SimulationResultOut)
def get_simulation_results(
    simulation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sim = _get_owned_simulation(simulation_id, current_user.id, db)

    if sim.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"Simulation failed: {sim.error_message or 'unknown error'}",
        )
    if sim.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Simulation is {sim.status} - results not available yet.",
        )

    return SimulationResultOut(
        id=sim.id,
        project_id=sim.project_id,
        status=sim.status,
        consumer_volume=sim.consumer_volume,
        results=sim.results_json,
        error_message=sim.error_message,
        created_at=sim.created_at,
        updated_at=sim.updated_at,
    )


@router.get("/project/{project_id}", response_model=list[SimulationStatusOut])
def list_project_simulations(
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

    sims = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .all()
    )
    return [SimulationStatusOut.model_validate(s) for s in sims]


def _get_owned_simulation(
    simulation_id: int,
    user_id: int,
    db: Session,
) -> Simulation:
    sim = (
        db.query(Simulation)
        .join(Project, Simulation.project_id == Project.id)
        .filter(Simulation.id == simulation_id, Project.user_id == user_id)
        .first()
    )
    if not sim:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return sim


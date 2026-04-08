import json
import re
from datetime import datetime, timezone

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.core.prompts import (
    ASSUMPTION_EXTRACTION_PROMPT,
    PREMORTEM_PROMPT,
    PROTOTYPE_GENERATION_PROMPT,
    build_simulation_summary,
)
from app.models.assumption import Assumption
from app.models.environment import Environment
from app.models.project import Project
from app.models.prototype import Prototype
from app.models.simulation import Simulation
from app.models.user import User
from app.schemas.assumption import (
    AssumptionExtractRequest,
    AssumptionListResponse,
    AssumptionOut,
)
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentSummary,
    ManualParams,
    SCENARIO_PRESETS,
)
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectOut
from app.schemas.premortem import FailureMode, PremortemOut, PremortemRequest
from app.schemas.prototype import FunnelEdge, FunnelGraph, FunnelNode, PrototypeOut

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


@router.post("/{project_id}/generate-prototype", response_model=PrototypeOut)
def generate_prototype(
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

    if not project.description or len(project.description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description is too short to generate a prototype",
        )

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            system=(
                "You are a world-class product designer and conversion rate expert. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Your HTML prototypes look like real funded startup products."
            ),
            messages=[
                {
                    "role": "user",
                    "content": PROTOTYPE_GENERATION_PROMPT.format(
                        description=project.description
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))

        html_content = parsed.get("html_content", "")
        funnel_data = parsed.get("funnel_graph", {})

        if not html_content or len(html_content) < 100:
            raise ValueError("Generated HTML is too short or empty")

        if not funnel_data.get("nodes") or not funnel_data.get("edges"):
            raise ValueError("Funnel graph is missing nodes or edges")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — please retry",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Prototype generation failed: {str(e)}",
        )

    existing = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )

    if existing:
        existing.html_content = html_content
        existing.funnel_graph_json = json.dumps(funnel_data)
        prototype = existing
    else:
        prototype = Prototype(
            project_id=project_id,
            html_content=html_content,
            funnel_graph_json=json.dumps(funnel_data),
        )
        db.add(prototype)

    project.status = "PROTOTYPE_GENERATED"
    project.prototype_html = html_content
    project.funnel_graph_json = json.dumps(funnel_data)

    db.commit()
    db.refresh(prototype)

    try:
        funnel_graph = FunnelGraph(
            nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
            edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
        )
    except Exception:
        funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=html_content,
        funnel_graph=funnel_graph,
    )


@router.get("/{project_id}/prototype", response_model=PrototypeOut)
def get_prototype(
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

    prototype = (
        db.query(Prototype).filter(Prototype.project_id == project_id).first()
    )
    if not prototype:
        raise HTTPException(
            status_code=404,
            detail="No prototype generated yet — call POST /generate-prototype first",
        )

    funnel_graph = None
    if prototype.funnel_graph_json:
        try:
            funnel_data = json.loads(prototype.funnel_graph_json)
            funnel_graph = FunnelGraph(
                nodes=[FunnelNode(**n) for n in funnel_data.get("nodes", [])],
                edges=[FunnelEdge(**e) for e in funnel_data.get("edges", [])],
            )
        except Exception:
            funnel_graph = None

    return PrototypeOut(
        id=prototype.id,
        project_id=project_id,
        html_content=prototype.html_content,
        funnel_graph=funnel_graph,
    )


@router.post("/{project_id}/premortem", response_model=PremortemOut)
def run_premortem(
    project_id: int,
    payload: PremortemRequest | None = None,
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
        payload.description_override if payload and payload.description_override else project.description
    )
    if not description or len(description.strip()) < 20:
        raise HTTPException(
            status_code=422,
            detail="Project description too short for pre-mortem analysis",
        )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .all()
    )

    latest_sim = (
        db.query(Simulation)
        .filter(
            Simulation.project_id == project_id,
            Simulation.status == "COMPLETED",
        )
        .order_by(Simulation.created_at.desc())
        .first()
    )

    assumptions_text = "\n".join(
        f"- [{a.sensitivity}] {a.text} (impact: {a.impact_score}/10)" for a in assumptions
    ) or "No assumptions extracted yet."

    simulation_summary = build_simulation_summary(
        latest_sim.results_json if latest_sim else None
    )

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2800,
            system=(
                "You are an elite startup failure analyst specialising in pre-mortem analysis. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            messages=[
                {
                    "role": "user",
                    "content": PREMORTEM_PROMPT.format(
                        description=description,
                        assumptions_text=assumptions_text,
                        simulation_summary=simulation_summary,
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()

        if raw.startswith("```"):
            raw = "\n".join(
                line for line in raw.split("\n") if not line.strip().startswith("```")
            )

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in Claude response")

        parsed = json.loads(json_match.group(0))
        raw_modes = parsed.get("failure_modes", [])

        if not isinstance(raw_modes, list) or len(raw_modes) == 0:
            raise ValueError("Claude returned empty failure_modes list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON - retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Pre-mortem analysis failed: {str(exc)}",
        )

    failure_modes: list[FailureMode] = []
    for item in raw_modes:
        try:
            fm = FailureMode(
                title=str(item.get("title", item.get("failure_mode", "Unknown failure"))).strip(),
                probability=float(item.get("probability", 0.5)),
                severity=str(item.get("severity", "MEDIUM")),
                trigger_condition=str(item.get("trigger_condition", "")).strip(),
                linked_assumption_texts=[
                    str(a).strip()
                    for a in item.get(
                        "linked_assumption_texts", item.get("linked_assumptions", [])
                    )
                ],
                intervention=str(
                    item.get("intervention", item.get("recommended_intervention", ""))
                ).strip(),
                intervention_impact=str(
                    item.get("intervention_impact", item.get("expected_impact", ""))
                ).strip(),
                earliest_signal=str(item.get("earliest_signal", "")).strip(),
            )
            if not fm.linked_assumption_texts:
                continue
            failure_modes.append(fm)
        except Exception:
            continue

    if not failure_modes:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid failure modes from Claude response",
        )

    failure_modes.sort(key=lambda f: f.probability, reverse=True)

    now = datetime.now(timezone.utc).isoformat()
    premortem_data = {
        "failure_modes": [fm.model_dump() for fm in failure_modes],
        "generated_at": now,
        "simulation_id": latest_sim.id if latest_sim else None,
        "assumptions_count": len(assumptions),
    }

    project.premortem_json = premortem_data
    project.status = "PREMORTEM_COMPLETE"
    db.commit()

    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=now,
    )


@router.get("/{project_id}/premortem", response_model=PremortemOut)
def get_premortem(
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

    data = getattr(project, "premortem_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No pre-mortem generated yet - call POST /premortem first",
        )

    failure_modes = [FailureMode(**fm) for fm in data.get("failure_modes", [])]
    critical_count = sum(1 for fm in failure_modes if fm.severity == "CRITICAL")

    return PremortemOut(
        project_id=project_id,
        failure_modes=failure_modes,
        total=len(failure_modes),
        critical_count=critical_count,
        generated_at=data.get("generated_at", ""),
    )


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
    status_code=200,
)
def create_or_update_environment(
    project_id: int,
    payload: EnvironmentCreate,
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

    if payload.mode.value == "SCENARIO" and payload.scenario_type:
        preset = SCENARIO_PRESETS.get(payload.scenario_type.value)
        effective = preset or ManualParams()
        if payload.manual_params:
            override = payload.manual_params.model_dump(exclude_none=True)
            merged = effective.model_dump()
            merged.update(override)
            effective = ManualParams(**merged)
    else:
        effective = payload.manual_params or ManualParams()

    existing = db.query(Environment).filter(Environment.project_id == project_id).first()

    if existing:
        existing.mode = payload.mode.value
        existing.consumer_volume = effective.consumer_volume
        existing.growth_rate_per_month = effective.growth_rate_per_month
        existing.average_order_value = effective.average_order_value
        existing.price_sensitivity = effective.price_sensitivity
        existing.market_maturity = effective.market_maturity
        existing.scenario_type = (
            payload.scenario_type.value if payload.scenario_type else None
        )
        existing.manual_params_json = effective.model_dump()
        env = existing
    else:
        env = Environment(
            project_id=project_id,
            mode=payload.mode.value,
            consumer_volume=effective.consumer_volume,
            growth_rate_per_month=effective.growth_rate_per_month,
            average_order_value=effective.average_order_value,
            price_sensitivity=effective.price_sensitivity,
            market_maturity=effective.market_maturity,
            scenario_type=(
                payload.scenario_type.value if payload.scenario_type else None
            ),
            manual_params_json=effective.model_dump(),
        )
        db.add(env)

    project.status = "ENVIRONMENT_SET"
    db.commit()
    db.refresh(env)
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments",
    response_model=EnvironmentOut,
)
def get_environment(
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

    env = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not env:
        raise HTTPException(
            status_code=404,
            detail="No environment configured. Call POST /environments first.",
        )
    return EnvironmentOut.model_validate(env)


@router.get(
    "/{project_id}/environments/presets",
    response_model=dict,
)
def get_scenario_presets(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all scenario preset configs so the frontend
    can display them to the user before they choose.
    """
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {name: preset.model_dump() for name, preset in SCENARIO_PRESETS.items()}


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

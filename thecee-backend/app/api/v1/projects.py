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
    COMPETITIVE_ANALYSIS_PROMPT,
    INTERVENTION_PROMPT,
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
from app.simulation.scored_assumption import score_assumptions, signal_quality_tier
from app.schemas.competitive import (
    CompetitiveAnalysisOut,
    CompetitiveAnalysisRequest,
    Competitor,
    GapAnalysis,
    MarketMap,
    VALID_POSITIONS,
)
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentOut,
    EnvironmentSummary,
    ManualParams,
    SCENARIO_PRESETS,
)
from app.schemas.intervention import Intervention, InterventionOut, InterventionRequest
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectOut
from app.schemas.premortem import FailureMode, PremortemOut, PremortemRequest
from app.schemas.prototype import FunnelEdge, FunnelGraph, FunnelNode, PrototypeOut
from app.schemas.stress_test import (
    AssumptionStressResult,
    StressTestOut,
    StressTestStatusOut,
)
from app.tasks.stress_test_tasks import run_assumption_stress_test

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

    # Score assumptions and compute signal quality for this extraction run.
    scored_list, hard_count, soft_flags, sq = score_assumptions(
        [
            {
                "id": a.id,
                "text": a.text,
                "category": a.category,
                "impact_score": a.impact_score,
            }
            for a in saved
        ]
    )

    # Build confidence distribution summary (count per tier).
    confidence_dist: dict[str, int] = {}
    for sa in scored_list:
        key = sa.claim_confidence.value
        confidence_dist[key] = confidence_dist.get(key, 0) + 1

    sq_tier = signal_quality_tier(sq)

    # Persist signal_quality on the most recent simulation for this project,
    # or update it when the next simulation is created (Step 37 task picks this up).
    # For now, write to the latest QUEUED/RUNNING simulation if one exists.
    latest_sim = (
        db.query(Simulation)
        .filter(Simulation.project_id == project_id)
        .order_by(Simulation.created_at.desc())
        .first()
    )
    if latest_sim is not None:
        latest_sim.signal_quality = sq
        latest_sim.claim_confidence_distribution = confidence_dist
        db.commit()

    # Apply personal accuracy adjustment from user_claim_accuracy_profiles
    # if the user has enough history (sample_count >= 3, reliability >= 0.40).
    # This is a read-only advisory enrichment — it does not modify saved rows.
    user_reliability_note: str | None = None
    try:
        from sqlalchemy import text as _text
        profile_rows = db.execute(
            _text(
                "SELECT architect_name, ema_delta, reliability_score, sample_count "
                "FROM user_claim_accuracy_profiles "
                "WHERE user_id = :uid AND sample_count >= 3 AND reliability_score >= 0.40"
            ),
            {"uid": current_user.id},
        ).fetchall()
        if profile_rows:
            user_reliability_note = (
                f"Personal accuracy profile active: {len(profile_rows)} architects calibrated."
            )
    except Exception:
        pass

    hidden_count = sum(1 for a in saved if a.is_hidden)

    return AssumptionListResponse(
        project_id=project_id,
        assumptions=[AssumptionOut.model_validate(a) for a in saved],
        total=len(saved),
        hidden_count=hidden_count,
        signal_quality=sq,
        signal_quality_tier=sq_tier,
        claim_confidence_distribution=confidence_dist,
        soft_contradiction_flags=soft_flags,
        message=(
            user_reliability_note or "Assumptions extracted successfully"
        ),
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

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    domain_findings_text = (
        "\n".join(
            [
                f"[{f.get('severity', 'INFO')}] {f.get('architect_name', '')} / "
                f"{f.get('cluster_name', '')}: {f.get('finding', '')} "
                f"(impact: {float(f.get('conversion_impact', 0) or 0):.3f})"
                for f in findings[:10]
            ]
        )
        if findings
        else "No domain findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
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
                        domain_findings_text=domain_findings_text,
                        primary_failure_domain=primary_fd,
                        highest_value_cluster=hv_name,
                        cluster_narrative=narrative,
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


@router.post("/{project_id}/stress-test", response_model=StressTestStatusOut)
def start_stress_test(
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

    environment = db.query(Environment).filter(Environment.project_id == project_id).first()
    if not environment:
        raise HTTPException(
            status_code=400,
            detail="Environment not configured. POST /environments first.",
        )

    critical_count = (
        db.query(Assumption)
        .filter(
            Assumption.project_id == project_id,
            Assumption.sensitivity.in_(["CRITICAL", "HIGH"]),
        )
        .count()
    )
    if critical_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No CRITICAL or HIGH assumptions found. Run assumption extraction first.",
        )

    task = run_assumption_stress_test.delay(project_id)
    return StressTestStatusOut(
        project_id=project_id,
        status="PENDING",
        task_id=task.id,
        result=None,
    )


@router.get("/{project_id}/stress-test", response_model=StressTestStatusOut)
def get_stress_test(
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

    raw = getattr(project, "stress_test_json", None)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail="No stress test run yet — call POST /stress-test first",
        )

    status_value = raw.get("status", "UNKNOWN")
    task_id = raw.get("task_id")

    if status_value != "COMPLETED":
        return StressTestStatusOut(
            project_id=project_id,
            status=status_value,
            task_id=task_id,
            result=None,
        )

    matrix = [AssumptionStressResult(**row) for row in raw.get("sensitivity_matrix", [])]
    shots = [AssumptionStressResult(**row) for row in raw.get("kill_shots", [])]

    result = StressTestOut(
        project_id=project_id,
        status="COMPLETED",
        sensitivity_matrix=matrix,
        kill_shots=shots,
        overall_risk_level=raw.get("overall_risk_level", "UNKNOWN"),
        baseline_conversion=raw.get("baseline_conversion", 0.0),
        assumptions_tested=raw.get("assumptions_tested", 0),
        generated_at=raw.get("generated_at", ""),
    )

    return StressTestStatusOut(
        project_id=project_id,
        status="COMPLETED",
        task_id=task_id,
        result=result,
    )


@router.delete("/{project_id}/stress-test")
def clear_stress_test(
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

    from sqlalchemy import text as sql_text

    db.execute(
        sql_text("UPDATE projects SET stress_test_json = NULL WHERE id = :id"),
        {"id": project_id},
    )
    db.commit()
    return {"message": "Stress test result cleared"}


@router.post("/{project_id}/interventions", response_model=InterventionOut)
def generate_interventions(
    project_id: int,
    payload: InterventionRequest | None = None,
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
            detail="Project description too short to generate interventions",
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

    premortem_data = getattr(project, "premortem_json", None)
    stress_test_data = getattr(project, "stress_test_json", None)

    context_used = {
        "assumptions": len(assumptions) > 0,
        "simulation": latest_sim is not None,
        "premortem": bool(premortem_data and premortem_data.get("failure_modes")),
        "stress_test": bool(stress_test_data and stress_test_data.get("kill_shots")),
    }

    results = latest_sim.results_json or {} if latest_sim else {}
    findings = results.get("domain_findings", [])
    narrative = results.get("cluster_narrative", "")
    primary_fd = results.get("primary_failure_domain", "unknown")
    hv_cluster = results.get("highest_value_cluster", {})

    ranked_findings_text = (
        "\n".join(
            [
                f"{i + 1}. {f.get('finding', '')} → {f.get('recommended_action', '')}"
                for i, f in enumerate(findings[:5])
            ]
        )
        if findings
        else "No findings available."
    )

    hv_name = (
        hv_cluster.get("name", "unknown") if isinstance(hv_cluster, dict) else str(hv_cluster)
    )

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            system=(
                "You are an elite startup growth advisor. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation. "
                "Every intervention you suggest is specific, executable, and tied to evidence."
            ),
            messages=[
                {
                    "role": "user",
                    "content": INTERVENTION_PROMPT.format(
                        highest_value_cluster=hv_name,
                        primary_failure_domain=primary_fd,
                        cluster_narrative=narrative or "No cluster narrative available.",
                        ranked_findings_text=ranked_findings_text,
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
        raw_items = parsed.get("interventions", [])
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise ValueError("Claude returned empty interventions list")

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Intervention generation failed: {str(exc)}",
        )

    interventions: list[Intervention] = []
    for idx, item in enumerate(raw_items):
        try:
            intervention = Intervention(
                id=str(item.get("id", f"int-{idx + 1:02d}")).strip()[:50],
                title=str(item.get("title", "")).strip(),
                description=str(item.get("description", "")).strip(),
                expected_impact=str(item.get("expected_impact", "")).strip(),
                difficulty=str(item.get("difficulty", "MEDIUM")),
                estimated_cost=str(item.get("estimated_cost", "Unknown")).strip(),
                linked_assumption=item.get("linked_assumption") or None,
                linked_failure_mode=item.get("linked_failure_mode") or None,
                priority_score=float(item.get("priority_score", 0.5)),
                time_to_implement=str(item.get("time_to_implement", "Unknown")).strip(),
                success_metric=str(item.get("success_metric", "")).strip(),
            )
            interventions.append(intervention)
        except Exception:
            continue

    if not interventions:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid interventions from Claude response",
        )

    interventions.sort(key=lambda item: item.priority_score, reverse=True)
    max_n = payload.max_interventions if payload else 10
    interventions = interventions[:max_n]

    quick_wins = [
        item for item in interventions if item.difficulty == "LOW" and item.priority_score > 0.70
    ]

    now = datetime.now(timezone.utc).isoformat()
    interventions_data = {
        "interventions": [iv.model_dump() for iv in interventions],
        "quick_wins": [qw.model_dump() for qw in quick_wins],
        "generated_at": now,
        "context_used": context_used,
        "simulation_id": latest_sim.id if latest_sim else None,
    }

    from sqlalchemy import text as sql_text

    try:
        db.execute(
            sql_text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS interventions_json JSONB;")
        )
        db.commit()
    except Exception:
        db.rollback()

    project.interventions_json = interventions_data
    project.status = "INTERVENTIONS_READY"
    db.commit()

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=now,
        context_used=context_used,
    )


@router.get("/{project_id}/interventions", response_model=InterventionOut)
def get_interventions(
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

    data = getattr(project, "interventions_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No interventions generated yet — call POST /interventions first",
        )

    interventions = [Intervention(**item) for item in data.get("interventions", [])]
    quick_wins = [Intervention(**item) for item in data.get("quick_wins", [])]

    return InterventionOut(
        project_id=project_id,
        interventions=interventions,
        total=len(interventions),
        quick_wins=quick_wins,
        generated_at=data.get("generated_at", ""),
        context_used=data.get("context_used", {}),
    )


@router.post("/{project_id}/competitive-analysis", response_model=CompetitiveAnalysisOut)
def run_competitive_analysis(
    project_id: int,
    payload: CompetitiveAnalysisRequest | None = None,
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
            detail="Project description too short for competitive analysis",
        )

    target_market = (
        payload.target_market if payload and payload.target_market else "Indian startup / SaaS / D2C market"
    )

    assumptions = (
        db.query(Assumption)
        .filter(Assumption.project_id == project_id)
        .order_by(Assumption.impact_score.desc())
        .limit(5)
        .all()
    )
    assumptions_text = (
        "\n".join(f"- {assumption.text}" for assumption in assumptions)
        if assumptions
        else "No assumptions available."
    )

    try:
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3200,
            system=(
                "You are a top-tier competitive strategy consultant with deep knowledge "
                "of Indian and global markets. "
                "You ALWAYS return valid JSON only. No markdown. No backticks. No explanation."
            ),
            messages=[
                {
                    "role": "user",
                    "content": COMPETITIVE_ANALYSIS_PROMPT.format(
                        description=description,
                        target_market=target_market,
                        assumptions_text=assumptions_text,
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

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Claude returned malformed JSON — retry the request",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Competitive analysis failed: {str(exc)}",
        )

    raw_competitors = parsed.get("competitors", [])
    if not isinstance(raw_competitors, list) or len(raw_competitors) == 0:
        raise HTTPException(
            status_code=500,
            detail="Claude returned no competitors — retry the request",
        )

    competitors: list[Competitor] = []
    for item in raw_competitors:
        try:
            competitors.append(
                Competitor(
                    name=str(item.get("name", "Unknown")).strip(),
                    category=str(item.get("category", "DIRECT")),
                    features=[str(feature) for feature in item.get("features", [])[:8]],
                    pricing=str(item.get("pricing", "Unknown")).strip(),
                    positioning=str(item.get("positioning", "")).strip(),
                    target_segment=str(item.get("target_segment", "")).strip(),
                    strengths=[str(strength) for strength in item.get("strengths", [])[:5]],
                    weaknesses=[str(weakness) for weakness in item.get("weaknesses", [])[:5]],
                    india_presence=str(item.get("india_presence", "MODERATE")),
                    threat_level=str(item.get("threat_level", "MEDIUM")),
                )
            )
        except Exception:
            continue

    if not competitors:
        raise HTTPException(
            status_code=500,
            detail="Could not parse any valid competitors from Claude response",
        )

    raw_gap = parsed.get("gap_analysis", {})
    gap_analysis = GapAnalysis(
        our_wins=[str(win) for win in raw_gap.get("our_wins", [])[:6]],
        our_losses=[str(loss) for loss in raw_gap.get("our_losses", [])[:6]],
        underserved_segments=[str(segment) for segment in raw_gap.get("underserved_segments", [])[:5]],
        key_differentiators=[str(item) for item in raw_gap.get("key_differentiators", [])[:5]],
        recommended_counter_moves=[str(move) for move in raw_gap.get("recommended_counter_moves", [])[:5]],
    )

    raw_map = parsed.get("market_map", {})
    first_competitor_name = competitors[0].name
    market_map = MarketMap(
        most_dangerous_competitor=str(
            raw_map.get("most_dangerous_competitor", first_competitor_name)
        ),
        easiest_to_displace=str(raw_map.get("easiest_to_displace", first_competitor_name)),
        most_similar_to_us=str(raw_map.get("most_similar_to_us", first_competitor_name)),
    )

    raw_position = str(parsed.get("overall_competitive_position", "MODERATE")).upper().strip()
    position = raw_position if raw_position in VALID_POSITIONS else "MODERATE"
    rationale = str(parsed.get("position_rationale", "")).strip()

    direct_count = sum(1 for competitor in competitors if competitor.category == "DIRECT")
    high_threat_count = sum(1 for competitor in competitors if competitor.threat_level == "HIGH")

    now = datetime.now(timezone.utc).isoformat()
    competitive_data = {
        "competitors": [competitor.model_dump() for competitor in competitors],
        "gap_analysis": gap_analysis.model_dump(),
        "market_map": market_map.model_dump(),
        "overall_competitive_position": position,
        "position_rationale": rationale,
        "generated_at": now,
        "target_market": target_market,
        "assumptions_used": len(assumptions),
    }

    from sqlalchemy import text as sql_text

    try:
        db.execute(sql_text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS competitive_json JSONB;"))
        db.commit()
    except Exception:
        db.rollback()

    project.competitive_json = competitive_data
    project.status = "COMPETITIVE_ANALYSIS_COMPLETE"
    db.commit()

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=rationale,
        direct_competitor_count=direct_count,
        high_threat_count=high_threat_count,
        generated_at=now,
    )


@router.get("/{project_id}/competitive-analysis", response_model=CompetitiveAnalysisOut)
def get_competitive_analysis(
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

    data = getattr(project, "competitive_json", None)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No competitive analysis generated yet — call POST /competitive-analysis first",
        )

    competitors = [Competitor(**item) for item in data.get("competitors", [])]
    gap_analysis = GapAnalysis(**data["gap_analysis"])
    market_map = MarketMap(**data["market_map"])
    position = data.get("overall_competitive_position", "MODERATE")

    return CompetitiveAnalysisOut(
        project_id=project_id,
        competitors=competitors,
        gap_analysis=gap_analysis,
        market_map=market_map,
        overall_competitive_position=position,
        position_rationale=data.get("position_rationale", ""),
        direct_competitor_count=sum(1 for competitor in competitors if competitor.category == "DIRECT"),
        high_threat_count=sum(1 for competitor in competitors if competitor.threat_level == "HIGH"),
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

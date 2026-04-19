import re

from anthropic import Anthropic
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.prompts import UI_GENERATION_PROMPT, validate_generated_html
from app.models.generated_ui import GeneratedUI
from app.models.project import Project
from app.models.ui_simulation_run import UISimulationRun
from app.models.user import User
from app.schemas.ui_generation import GeneratedUIResponse, UIRefineRequest, UIGenerateRequest

router = APIRouter(tags=["ui-generation"])
client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

ALLOWED_CDNS = ["tailwindcss", "alpinejs", "cdn.tailwindcss", "jsdelivr.net/npm/alpinejs"]


def _strip_unsafe_scripts(html: str) -> str:
    def is_safe(tag: str) -> bool:
        return any(cdn in tag for cdn in ALLOWED_CDNS)

    return re.sub(
        r'<script[^>]*src=["\'][^"\']+["\'][^>]*></script>',
        lambda m: m.group(0) if is_safe(m.group(0)) else "",
        html,
        flags=re.IGNORECASE,
    )


def _extract_html(raw: str) -> str:
    match = re.search(r"<!DOCTYPE html>.*?</html>", raw, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0)
    match = re.search(r"<html.*?</html>", raw, re.DOTALL | re.IGNORECASE)
    return match.group(0) if match else raw.strip()


def _inject_tracking(html: str) -> str:
    script = """<script>
document.addEventListener('click',function(e){
    var el=e.target.closest('[data-thecee-id]');
    if(el) console.log('TheCee:',el.getAttribute('data-thecee-id'));
});
</script>"""
    if "</body>" in html:
        return html.replace("</body>", script + "</body>")
    return html + script


@router.post("/projects/{project_id}/generate-ui", response_model=GeneratedUIResponse)
async def generate_ui(
    project_id: int,
    body: UIGenerateRequest,
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

    prompt = UI_GENERATION_PROMPT.format(
        description=(project.description or "") + "\n\n" + body.prompt,
        product_type=body.product_type,
        target_segment=body.target_demographic or "general Indian consumer",
        price_point=body.price_point or "competitive",
    )

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude call failed: {e}") from e

    html = _strip_unsafe_scripts(_extract_html(raw))
    ok, err = validate_generated_html(html)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Generated HTML failed validation: {err}")

    ui = GeneratedUI(
        project_id=project_id,
        prompt=body.prompt,
        html_content=html,
        version=1,
        product_type=body.product_type,
        pages_generated=len(body.pages_required),
    )
    db.add(ui)
    db.commit()
    db.refresh(ui)

    return GeneratedUIResponse(
        id=ui.id,
        project_id=project_id,
        version=ui.version,
        html_preview_url=f"/api/v1/generated-uis/{ui.id}/serve",
        pages_detected=body.pages_required,
    )


@router.post("/projects/{project_id}/generate-ui/refine", response_model=GeneratedUIResponse)
async def refine_ui(
    project_id: int,
    body: UIRefineRequest,
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

    existing = (
        db.query(GeneratedUI)
        .filter(
            GeneratedUI.id == body.generated_ui_id,
            GeneratedUI.project_id == project_id,
        )
        .first()
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Generated UI not found")

    refine_prompt = f"""You are refining an existing HTML prototype.
Current HTML:
{existing.html_content[:3000]}

Refinement instruction: {body.refinement_prompt}

Return ONLY the complete updated HTML. Keep all data-thecee-id attributes.
Maintain Tailwind CSS and Alpine.js CDN links.
No markdown, no explanation."""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=6000,
            messages=[{"role": "user", "content": refine_prompt}],
        )
        raw = resp.content[0].text.strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude call failed: {e}") from e

    html = _strip_unsafe_scripts(_extract_html(raw))
    ok, err = validate_generated_html(html)
    if not ok:
        raise HTTPException(status_code=400, detail=f"Refined HTML failed validation: {err}")

    new_ui = GeneratedUI(
        project_id=project_id,
        prompt=body.refinement_prompt,
        html_content=html,
        version=existing.version + 1,
        product_type=existing.product_type,
        pages_generated=existing.pages_generated,
    )
    db.add(new_ui)
    db.commit()
    db.refresh(new_ui)

    return GeneratedUIResponse(
        id=new_ui.id,
        project_id=project_id,
        version=new_ui.version,
        html_preview_url=f"/api/v1/generated-uis/{new_ui.id}/serve",
        pages_detected=["home", "product", "checkout"],
    )


@router.get("/projects/{project_id}/generated-uis")
async def list_generated_uis(
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

    uis = (
        db.query(GeneratedUI)
        .filter(GeneratedUI.project_id == project_id)
        .order_by(GeneratedUI.version.desc())
        .all()
    )

    return {
        "uis": [
            {
                "id": ui.id,
                "version": ui.version,
                "product_type": ui.product_type,
                "pages_generated": ui.pages_generated,
                "html_preview_url": f"/api/v1/generated-uis/{ui.id}/serve",
                "created_at": ui.created_at.isoformat() if ui.created_at else None,
            }
            for ui in uis
        ]
    }


@router.get("/generated-uis/{ui_id}")
async def get_generated_ui(
    ui_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ui = db.query(GeneratedUI).filter(GeneratedUI.id == ui_id).first()
    if not ui:
        raise HTTPException(status_code=404, detail="UI not found")
    owned = (
        db.query(Project)
        .filter(Project.id == ui.project_id, Project.user_id == current_user.id)
        .first()
    )
    if not owned:
        raise HTTPException(status_code=404, detail="UI not found")

    return {
        "id": ui.id,
        "project_id": ui.project_id,
        "version": ui.version,
        "product_type": ui.product_type,
        "pages_generated": ui.pages_generated,
        "prompt": ui.prompt,
        "html_preview_url": f"/api/v1/generated-uis/{ui.id}/serve",
        "created_at": ui.created_at.isoformat() if ui.created_at else None,
    }


@router.get("/generated-uis/{ui_id}/serve", response_class=HTMLResponse)
async def serve_generated_ui(
    ui_id: int,
    db: Session = Depends(get_db),
):
    ui = db.query(GeneratedUI).filter(GeneratedUI.id == ui_id).first()
    if not ui:
        raise HTTPException(status_code=404, detail="UI not found")
    return HTMLResponse(content=_inject_tracking(ui.html_content))


@router.post("/projects/{project_id}/generated-uis/{ui_id}/simulate")
async def start_ui_simulation(
    project_id: int,
    ui_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.tasks.ui_simulation_tasks import run_ui_simulation

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    ui = (
        db.query(GeneratedUI)
        .filter(
            GeneratedUI.id == ui_id,
            GeneratedUI.project_id == project_id,
        )
        .first()
    )
    if not ui:
        raise HTTPException(status_code=404, detail="Generated UI not found")

    run = UISimulationRun(
        project_id=project_id,
        generated_ui_id=ui_id,
        status="QUEUED",
        agent_count=1040,  # 52 clusters × ~20 agents each
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    serve_url = (
        f"https://simulation-production-c81f.up.railway.app/api/v1/generated-uis/{ui_id}/serve"
    )

    run_ui_simulation.delay(
        ui_simulation_run_id=run.id,
        generated_ui_id=ui_id,
        project_id=project_id,
        product_type=ui.product_type or "saas",
        agents_per_cluster=20,
        serve_url=serve_url,
    )

    return {
        "ui_simulation_run_id": run.id,
        "status": "QUEUED",
        "message": "UI simulation started — check /ui-simulation-runs/{id} for results",
    }


@router.get("/projects/{project_id}/ui-simulation-runs/{run_id}")
async def get_ui_simulation_run(
    project_id: int,
    run_id: int,
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

    run = (
        db.query(UISimulationRun)
        .filter(
            UISimulationRun.id == run_id,
            UISimulationRun.project_id == project_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "status": run.status,
        "agent_count": run.agent_count,
        "results": run.results_json,
        "conductor_result": run.conductor_result_json,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


@router.get("/projects/{project_id}/ui-simulation-runs/{run_id}/heatmap")
async def get_heatmap(
    project_id: int,
    run_id: int,
    cluster_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.simulation.heatmap import HeatmapEngine

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = (
        db.query(UISimulationRun)
        .filter(
            UISimulationRun.id == run_id,
            UISimulationRun.project_id == project_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "COMPLETED":
        return {"status": run.status, "message": "Simulation not yet complete"}

    if not run.generated_ui_id:
        raise HTTPException(status_code=400, detail="Run has no generated UI")

    query = """
        SELECT agent_cluster_id, events_json, converted
        FROM ui_simulation_sessions
        WHERE generated_ui_id = :ui_id
    """
    params: dict = {"ui_id": run.generated_ui_id}
    if cluster_id:
        query += " AND agent_cluster_id = :cid"
        params["cid"] = cluster_id

    rows = db.execute(text(query), params).mappings().all()
    sessions = [
        {
            "agent_cluster_id": r["agent_cluster_id"],
            "events_json": r["events_json"],
            "converted": r["converted"],
        }
        for r in rows
    ]

    engine = HeatmapEngine()
    result = engine.generate(run.generated_ui_id, sessions)
    return engine.to_dict(result)


@router.get("/projects/{project_id}/ui-simulation-runs/{run_id}/funnel")
async def get_funnel_analytics(
    project_id: int,
    run_id: int,
    cluster_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = (
        db.query(UISimulationRun)
        .filter(
            UISimulationRun.id == run_id,
            UISimulationRun.project_id == project_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "COMPLETED":
        return {"status": run.status, "message": "Simulation not yet complete"}

    if not run.generated_ui_id:
        raise HTTPException(status_code=400, detail="Run has no generated UI")

    query = (
        "SELECT agent_cluster_id, events_json, converted FROM ui_simulation_sessions "
        "WHERE generated_ui_id = :uid"
    )
    params: dict = {"uid": run.generated_ui_id}
    if cluster_id:
        query += " AND agent_cluster_id = :cid"
        params["cid"] = cluster_id

    rows = db.execute(text(query), params).mappings().all()
    sessions = [
        {
            "agent_cluster_id": r["agent_cluster_id"],
            "events_json": r["events_json"],
            "converted": r["converted"],
        }
        for r in rows
    ]

    engine = FunnelAnalyticsEngine()
    result = engine.generate(run.generated_ui_id, sessions)
    return engine.to_dict(result)


@router.get("/projects/{project_id}/ui-simulation-runs/{run_id}/channel-attribution")
async def get_channel_attribution(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.simulation.channel_attribution import ChannelAttributionEngine
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.product_type import ProductType

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = (
        db.query(UISimulationRun)
        .filter(
            UISimulationRun.id == run_id,
            UISimulationRun.project_id == project_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "COMPLETED":
        return {"status": run.status, "message": "Simulation not yet complete"}

    if not run.generated_ui_id:
        raise HTTPException(status_code=400, detail="Run has no generated UI")

    product_type_str = (run.results_json or {}).get("product_type", "saas")
    try:
        pt = ProductType(product_type_str)
    except Exception:
        pt = ProductType.SAAS

    registry = ClusterRegistry()
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={"product_type": pt.value},
        assumptions=[],
        product_type=pt,
    )
    conductor_results = {
        cid: {
            name: {"metrics": out.metrics, "flags": out.flags}
            for name, out in arch.items()
        }
        for cid, arch in cond_result.cluster_results.items()
    }
    cluster_list = [
        {
            "cluster_id": c.cluster_id,
            "name": c.name,
            "population_weight": c.population_weight,
        }
        for c in registry.all_clusters()
    ]

    engine = ChannelAttributionEngine()
    result = engine.generate(
        generated_ui_id=run.generated_ui_id,
        conductor_results=conductor_results,
        cluster_registry=cluster_list,
        product_type=product_type_str,
    )
    return engine.to_dict(result)


@router.get("/projects/{project_id}/ui-simulation-runs/{run_id}/retention")
async def get_retention_churn(
    project_id: int,
    run_id: int,
    aov: float = 999.0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.product_type import ProductType
    from app.simulation.retention_churn import RetentionChurnEngine

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = (
        db.query(UISimulationRun)
        .filter(
            UISimulationRun.id == run_id,
            UISimulationRun.project_id == project_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "COMPLETED":
        return {"status": run.status, "message": "Simulation not yet complete"}

    if not run.generated_ui_id:
        raise HTTPException(status_code=400, detail="Run has no generated UI")

    product_type_str = (run.results_json or {}).get("product_type", "saas")
    try:
        pt = ProductType(product_type_str)
    except Exception:
        pt = ProductType.SAAS

    registry = ClusterRegistry()
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[],
        env_params={"average_order_value": aov, "product_type": pt.value},
        assumptions=[],
        product_type=pt,
    )
    conductor_results = {
        cid: {
            name: {"metrics": out.metrics, "flags": out.flags}
            for name, out in arch_outputs.items()
        }
        for cid, arch_outputs in cond_result.cluster_results.items()
    }
    cluster_list = [
        {
            "cluster_id": c.cluster_id,
            "name": c.name,
            "population_weight": c.population_weight,
        }
        for c in registry.all_clusters()
    ]

    engine = RetentionChurnEngine()
    result = engine.generate(
        generated_ui_id=run.generated_ui_id,
        conductor_results=conductor_results,
        cluster_registry=cluster_list,
        aov=aov,
        product_type=product_type_str,
    )
    return engine.to_dict(result)

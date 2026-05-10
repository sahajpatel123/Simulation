import hmac
import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.claude_client import claude_call_with_fallback
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.prompts import UI_GENERATION_PROMPT, UI_REFINE_PROMPT_TEMPLATE, UI_REFINE_SYSTEM
from app.models.generated_ui import GeneratedUI
from app.models.project import Project
from app.models.ui_simulation_run import UISimulationRun
from app.models.user import User
from app.schemas.ui_generation import GeneratedUIResponse, UIRefineRequest, UIGenerateRequest

router = APIRouter(tags=["ui-generation"])
logger = logging.getLogger("thecee.ui_generation")

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}
_HTML_200 = {200: {"description": "HTML document", "content": {"text/html": {}}}}
_PDF_200 = {200: {"description": "PDF file", "content": {"application/pdf": {}}}}

ALLOWED_CDNS = ["tailwindcss", "cdn.tailwindcss"]
TAILWIND_CDN = '<script src="https://cdn.tailwindcss.com"></script>'


def _new_preview_token() -> str:
    return secrets.token_urlsafe(32)


def _preview_url(ui: GeneratedUI) -> str:
    if ui.preview_token:
        return f"/api/v1/generated-uis/{ui.id}/serve?preview_token={ui.preview_token}"
    return f"/api/v1/generated-uis/{ui.id}/serve"


def _is_valid_preview_token(ui: GeneratedUI, preview_token: str | None) -> bool:
    if not ui.preview_token or not preview_token:
        return False
    return hmac.compare_digest(ui.preview_token, preview_token)


def _strip_unsafe_scripts(html: str) -> str:
    def is_safe(tag: str) -> bool:
        return any(cdn in tag for cdn in ALLOWED_CDNS)

    return re.sub(
        r'<script[^>]*src=["\'][^"\']+["\'][^>]*></script>',
        lambda m: m.group(0) if is_safe(m.group(0)) else "",
        html,
        flags=re.IGNORECASE,
    )


def _strip_markdown_fences(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:html|HTML)?\s*\n?", "", s)
    s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _coerce_to_html_doc(raw: str) -> str:
    """Always return a usable HTML document.

    Handles markdown fences, fragments, and truncated outputs (no closing tags)
    so a single missing token never bricks the prototype.
    """
    s = _strip_markdown_fences(raw)

    # Best case: complete document.
    m = re.search(r"<!DOCTYPE\s+html>.*?</html>", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0)
    m = re.search(r"<html\b.*?</html>", s, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(0)

    # Truncated document: starts with a doc opener but has no closing tag.
    if re.search(r"<!DOCTYPE\s+html>|<html\b", s, re.IGNORECASE):
        if not re.search(r"</body\s*>", s, re.IGNORECASE):
            s += "\n</body>"
        if not re.search(r"</html\s*>", s, re.IGNORECASE):
            s += "\n</html>"
        return s

    # Pure fragment from the model — wrap it.
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head><body>"
        f"{s}"
        "</body></html>"
    )


def _ensure_cdns(html: str) -> str:
    """Guarantee the Tailwind CDN is present — the prototype's styling depends on it."""
    lower = html.lower()
    if "cdn.tailwindcss.com" in lower or "tailwindcss" in lower:
        return html
    if re.search(r"</head\s*>", html, re.IGNORECASE):
        return re.sub(r"</head\s*>", TAILWIND_CDN + "</head>", html, count=1, flags=re.IGNORECASE)
    if re.search(r"<body\b[^>]*>", html, re.IGNORECASE):
        return re.sub(r"(<body\b[^>]*>)", r"\1" + TAILWIND_CDN, html, count=1, flags=re.IGNORECASE)
    return TAILWIND_CDN + html


def _has_tid(html: str, tid: str) -> bool:
    return bool(re.search(rf'data-thecee-id\s*=\s*["\']{re.escape(tid)}["\']', html, re.IGNORECASE))


def _inject_attr(html: str, tag_pattern: str, attr: str) -> str:
    m = re.search(tag_pattern, html, re.IGNORECASE)
    if not m:
        return html
    return html[: m.end()] + " " + attr + html[m.end():]


def _ensure_tracking_ids(html: str) -> str:
    """Guarantee the three required tracking attributes exist somewhere in the document.

    Prefer attaching to a real button/section/form. If none exists for a given role,
    create a hidden marker so downstream simulation code never crashes.
    """
    if not _has_tid(html, "cta-primary"):
        if re.search(r"<button\b(?![^>]*data-thecee-id)", html, re.IGNORECASE):
            html = _inject_attr(html, r"<button\b(?![^>]*data-thecee-id)", 'data-thecee-id="cta-primary"')
        elif re.search(r"<a\b(?![^>]*data-thecee-id)", html, re.IGNORECASE):
            html = _inject_attr(html, r"<a\b(?![^>]*data-thecee-id)", 'data-thecee-id="cta-primary"')

    if not _has_tid(html, "checkout-form"):
        if re.search(r"<form\b(?![^>]*data-thecee-id)", html, re.IGNORECASE):
            html = _inject_attr(html, r"<form\b(?![^>]*data-thecee-id)", 'data-thecee-id="checkout-form"')

    if not _has_tid(html, "pricing-section"):
        if re.search(r"<section\b(?![^>]*data-thecee-id)", html, re.IGNORECASE):
            html = _inject_attr(html, r"<section\b(?![^>]*data-thecee-id)", 'data-thecee-id="pricing-section"')
        elif re.search(r"<div\b(?![^>]*data-thecee-id)", html, re.IGNORECASE):
            html = _inject_attr(html, r"<div\b(?![^>]*data-thecee-id)", 'data-thecee-id="pricing-section"')

    # Last-resort hidden markers: never let downstream sim code miss a hook.
    markers = ""
    for tid in ("cta-primary", "pricing-section", "checkout-form"):
        if not _has_tid(html, tid):
            markers += f'<span data-thecee-id="{tid}" style="display:none" aria-hidden="true"></span>'
    if markers:
        if re.search(r"</body\s*>", html, re.IGNORECASE):
            html = re.sub(r"</body\s*>", markers + "</body>", html, count=1, flags=re.IGNORECASE)
        else:
            html += markers
    return html


def _build_safe_html(raw: str) -> str:
    """Coerce raw model output into a self-contained, valid prototype document.

    Pipeline:
      1. Coerce to a complete HTML document (handles fences, fragments, truncation).
      2. Strip non-allowlisted external scripts.
      3. Inject Tailwind + Alpine CDNs if missing.
      4. Guarantee the three required tracking attributes exist.
    """
    doc = _coerce_to_html_doc(raw)
    doc = _strip_unsafe_scripts(doc)
    doc = _ensure_cdns(doc)
    doc = _ensure_tracking_ids(doc)
    return doc


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


@router.post(
    "/projects/{project_id}/generate-ui",
    response_model=GeneratedUIResponse,
    summary="Generate a Tailwind HTML UI prototype for a project",
)
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

    out = claude_call_with_fallback(
        [{"role": "user", "content": prompt}],
        model="claude-sonnet-4-6",
        max_tokens=8192,
        fallback_key="ui_generation",
        timeout=240,
    )
    if out.get("error"):
        raise HTTPException(
            status_code=503,
            detail=str(out.get("error", "Generation timed out. Please retry.")),
        )
    raw = (out.get("content") or "").strip()
    if len(raw) < 80:
        logger.warning("generate-ui: empty/short model output (raw_len=%s)", len(raw))
        raise HTTPException(
            status_code=502,
            detail="Generator returned no content. Please retry.",
        )

    html = _build_safe_html(raw)
    logger.info(
        "generate-ui ok project=%s raw_len=%s html_len=%s",
        project_id,
        len(raw),
        len(html),
    )

    ui = GeneratedUI(
        project_id=project_id,
        prompt=body.prompt,
        html_content=html,
        version=1,
        product_type=body.product_type,
        pages_generated=len(body.pages_required),
        preview_token=_new_preview_token(),
    )
    db.add(ui)
    db.commit()
    db.refresh(ui)

    return GeneratedUIResponse(
        id=ui.id,
        project_id=project_id,
        version=ui.version,
        html_preview_url=_preview_url(ui),
        html_content=html,
        pages_detected=body.pages_required,
    )


@router.post(
    "/projects/{project_id}/generate-ui/refine",
    response_model=GeneratedUIResponse,
    summary="Refine an existing generated UI with a new instruction",
)
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

    refine_prompt = UI_REFINE_PROMPT_TEMPLATE.format(
        html=existing.html_content or "",
        instruction=body.refinement_prompt,
    )

    out = claude_call_with_fallback(
        [{"role": "user", "content": refine_prompt}],
        model="claude-sonnet-4-6",
        max_tokens=8192,
        fallback_key="ui_generation",
        timeout=240,
        system=UI_REFINE_SYSTEM,
    )
    if out.get("error"):
        raise HTTPException(
            status_code=503,
            detail=str(out.get("error", "Generation timed out. Please retry.")),
        )
    raw = (out.get("content") or "").strip()
    if len(raw) < 80:
        logger.warning("refine-ui: empty/short model output (raw_len=%s)", len(raw))
        raise HTTPException(
            status_code=502,
            detail="Generator returned no content. Please retry.",
        )

    html = _build_safe_html(raw)

    new_ui = GeneratedUI(
        project_id=project_id,
        prompt=body.refinement_prompt,
        html_content=html,
        version=existing.version + 1,
        product_type=existing.product_type,
        pages_generated=existing.pages_generated,
        preview_token=_new_preview_token(),
    )
    db.add(new_ui)
    db.commit()
    db.refresh(new_ui)

    return GeneratedUIResponse(
        id=new_ui.id,
        project_id=project_id,
        version=new_ui.version,
        html_preview_url=_preview_url(new_ui),
        html_content=html,
        pages_detected=["home", "product", "checkout"],
    )


@router.get(
    "/projects/{project_id}/generated-uis",
    summary="List generated UIs and preview URLs for a project",
    responses=_JSON_200,
)
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
                "html_preview_url": _preview_url(ui),
                "html_content": ui.html_content,
                "created_at": ui.created_at.isoformat() if ui.created_at else None,
            }
            for ui in uis
        ]
    }


@router.get(
    "/generated-uis/{ui_id}",
    summary="Get metadata for a generated UI",
    responses=_JSON_200,
)
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
        "html_preview_url": _preview_url(ui),
        "created_at": ui.created_at.isoformat() if ui.created_at else None,
    }


@router.get(
    "/generated-uis/{ui_id}/serve",
    response_class=HTMLResponse,
    summary="Serve generated HTML in the browser with a preview token",
    responses=_HTML_200,
)
async def serve_generated_ui(
    ui_id: int,
    preview_token: str | None = None,
    db: Session = Depends(get_db),
):
    ui = db.query(GeneratedUI).filter(GeneratedUI.id == ui_id).first()
    if not ui:
        raise HTTPException(status_code=404, detail="UI not found")
    if not _is_valid_preview_token(ui, preview_token):
        raise HTTPException(status_code=404, detail="UI not found")

    # Allow the frontend to embed this document in an iframe while blocking
    # all other origins.  frame-ancestors supersedes X-Frame-Options in all
    # modern browsers; the global middleware skips X-Frame-Options: DENY for
    # /serve paths so older browsers are also covered.
    frontend_origin = settings.FRONTEND_URL.rstrip("/")
    csp_parts = [
        "default-src 'none'",
        # Tailwind Play CDN and Alpine.js both rely on eval/inline execution.
        "script-src 'unsafe-inline' 'unsafe-eval' "
        "https://cdn.tailwindcss.com https://unpkg.com "
        "https://cdn.jsdelivr.net https://esm.sh",
        "style-src 'unsafe-inline' "
        "https://cdn.tailwindcss.com https://fonts.googleapis.com "
        "https://cdn.jsdelivr.net",
        "font-src data: https://fonts.gstatic.com https://cdn.jsdelivr.net",
        "img-src data: blob:",
        "connect-src 'none'",
        # Only the TheCee frontend (and the API itself for direct opens) may frame this document.
        f"frame-ancestors 'self' {frontend_origin}",
        "form-action 'none'",
        "object-src 'none'",
        "base-uri 'none'",
    ]
    headers = {
        "Content-Security-Policy": "; ".join(csp_parts),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        # Cache generated UIs aggressively — content is immutable per version.
        "Cache-Control": "private, max-age=3600, immutable",
    }
    return HTMLResponse(content=_inject_tracking(ui.html_content), headers=headers)


@router.post(
    "/projects/{project_id}/generated-uis/{ui_id}/simulate",
    summary="Start a browser-based UI simulation run",
    responses=_JSON_200,
)
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

    serve_url = f"{settings.PUBLIC_API_BASE_URL.rstrip('/')}{_preview_url(ui)}"

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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}",
    summary="Get a UI simulation run status and results JSON",
    responses=_JSON_200,
)
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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/heatmap",
    summary="Click heatmap for a completed UI simulation",
    responses=_JSON_200,
)
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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/funnel",
    summary="Funnel stage analytics for a UI simulation",
    responses=_JSON_200,
)
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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/channel-attribution",
    summary="Channel attribution vs conductor for a UI run",
    responses=_JSON_200,
)
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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/retention",
    summary="Retention and churn model for a UI run",
    responses=_JSON_200,
)
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


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/infra-scaling",
    summary="Infra load scaling estimate from UI simulation traffic",
    responses=_JSON_200,
)
async def get_infra_scaling(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.infra_scaling import InfraScalingEngine
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
    overall_cr = (run.results_json or {}).get("overall_conversion_rate", 0.05)

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

    retention_engine = RetentionChurnEngine()
    retention_result = retention_engine.generate(
        generated_ui_id=run.generated_ui_id,
        conductor_results=conductor_results,
        cluster_registry=cluster_list,
        product_type=product_type_str,
    )
    retention_dict = retention_engine.to_dict(retention_result)
    cluster_profiles = retention_dict["cluster_profiles"]

    engine = InfraScalingEngine()
    result = engine.generate(
        generated_ui_id=run.generated_ui_id,
        product_type=product_type_str,
        cluster_profiles=cluster_profiles,
        overall_conversion=float(overall_cr),
    )
    return engine.to_dict(result)


@router.get(
    "/projects/{project_id}/ui-simulation-runs/{run_id}/report.pdf",
    summary="Download combined UI simulation PDF report",
    responses=_PDF_200,
)
async def get_simulation_report_pdf(
    project_id: int,
    run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.reports.simulation_report import SimulationReportGenerator
    from app.simulation.channel_attribution import ChannelAttributionEngine
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.funnel_analytics import FunnelAnalyticsEngine
    from app.simulation.heatmap import HeatmapEngine
    from app.simulation.infra_scaling import InfraScalingEngine
    from app.simulation.pricing_sensitivity import PricingSensitivityEngine
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
        raise HTTPException(status_code=400, detail="Simulation not yet complete")

    if not run.generated_ui_id:
        raise HTTPException(status_code=400, detail="Run has no generated UI")

    project_name = project.title if project else f"Project {project_id}"

    results_json = run.results_json or {}
    product_type_str = results_json.get("product_type", "saas")
    aov = float(results_json.get("aov", 999))
    overall_cr = float(results_json.get("overall_conversion_rate", 0.05))

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

    rows = db.execute(
        text(
            "SELECT agent_cluster_id, events_json, converted FROM ui_simulation_sessions "
            "WHERE generated_ui_id=:uid"
        ),
        {"uid": run.generated_ui_id},
    ).mappings().all()
    sessions = [
        {
            "agent_cluster_id": r["agent_cluster_id"],
            "events_json": r["events_json"],
            "converted": r["converted"],
        }
        for r in rows
    ]

    funnel_eng = FunnelAnalyticsEngine()
    funnel_r = funnel_eng.generate(run.generated_ui_id, sessions)
    funnel_d = funnel_eng.to_dict(funnel_r)

    heatmap_eng = HeatmapEngine()
    heatmap_r = heatmap_eng.generate(run.generated_ui_id, sessions)
    heatmap_d = heatmap_eng.to_dict(heatmap_r)

    pricing_eng = PricingSensitivityEngine()
    pricing_r = pricing_eng.generate(run.generated_ui_id, conductor_results, cluster_list, aov=aov)
    pricing_d = pricing_eng.to_dict(pricing_r)

    retention_eng = RetentionChurnEngine()
    retention_r = retention_eng.generate(
        run.generated_ui_id,
        conductor_results,
        cluster_list,
        aov=aov,
        product_type=product_type_str,
    )
    retention_d = retention_eng.to_dict(retention_r)

    channel_eng = ChannelAttributionEngine()
    channel_r = channel_eng.generate(
        run.generated_ui_id, conductor_results, cluster_list, product_type=product_type_str
    )
    channel_d = channel_eng.to_dict(channel_r)

    infra_eng = InfraScalingEngine()
    infra_r = infra_eng.generate(
        run.generated_ui_id,
        product_type_str,
        retention_d["cluster_profiles"],
        overall_conversion=overall_cr,
    )
    infra_d = infra_eng.to_dict(infra_r)

    simulation_data = {**results_json, **(run.conductor_result_json or {})}
    gen = SimulationReportGenerator()
    pdf_b = gen.generate(
        simulation_data=simulation_data,
        conductor_data=run.conductor_result_json or {},
        funnel_data=funnel_d,
        heatmap_data=heatmap_d,
        pricing_data=pricing_d,
        retention_data=retention_d,
        channel_data=channel_d,
        infra_data=infra_d,
        project_name=project_name,
    )

    return Response(
        content=pdf_b,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="thecee-report-{run_id}.pdf"'},
    )

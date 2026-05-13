import hmac
import logging
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.claude_client import claude_call_with_fallback
from app.core.config import settings
from app.core.css_templates import select_layout_archetype
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limiter import rate_limit
from app.core.prompts import (
    UI_GENERATION_PROMPT,
    UI_GENERATION_SYSTEM,
    UI_REFINE_PROMPT_TEMPLATE,
    UI_REFINE_SYSTEM,
    validate_generated_html,
)
from app.api.v1.common import get_owned_project
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

ALLOWED_CDNS = ["tailwindcss", "cdn.tailwindcss", "images.unsplash.com", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com"]
TAILWIND_CDN = '<script src="https://cdn.tailwindcss.com"></script>'


def _load_conductor_results(
    run: UISimulationRun,
) -> tuple[dict[str, dict[str, dict]], list[dict[str, Any]], str]:
    """Load conductor results from cached run data, avoiding recomputation.

    Returns (cluster_results, cluster_list, product_type_str).
    Falls back to fresh Conductor run if cache is incomplete.
    """
    from app.simulation.clusters.registry import ClusterRegistry
    from app.simulation.conductor import Conductor
    from app.simulation.product_type import ProductType

    cached = run.conductor_result_json or {}

    if cached.get("cluster_results"):
        cluster_results = cached["cluster_results"]
        registry = ClusterRegistry()
        cluster_list = [
            {"cluster_id": c.cluster_id, "name": c.name, "population_weight": c.population_weight}
            for c in registry.all_clusters()
        ]
        product_type_str = cached.get("product_type", "saas")
        return cluster_results, cluster_list, product_type_str

    # Fallback: run fresh Conductor
    product_type_str = (run.results_json or {}).get("product_type", "saas")
    try:
        pt = ProductType(product_type_str)
    except Exception:
        pt = ProductType.SAAS
    conductor = Conductor()
    cond_result = conductor.run(
        agents=[], env_params={"product_type": pt.value}, assumptions=[], product_type=pt,
    )
    cluster_results = {
        cid: {name: {"metrics": o.metrics, "flags": o.flags} for name, o in arch.items()}
        for cid, arch in cond_result.cluster_results.items()
    }
    registry = ClusterRegistry()
    cluster_list = [
        {"cluster_id": c.cluster_id, "name": c.name, "population_weight": c.population_weight}
        for c in registry.all_clusters()
    ]
    return cluster_results, cluster_list, product_type_str


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


def _lock_project_for_ui_version(db: Session, project_id: int, user_id: int) -> None:
    locked = (
        db.query(Project.id)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .with_for_update()
        .first()
    )
    if not locked:
        raise HTTPException(status_code=404, detail="Project not found")


def _next_ui_version(db: Session, project_id: int) -> int:
    latest = db.query(func.max(GeneratedUI.version)).filter(GeneratedUI.project_id == project_id).scalar()
    return int(latest or 0) + 1


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


def _inject_base_css(html: str, css: str) -> str:
    html = re.sub(
        r'<style\b[^>]*\bid=["\']thecee-base["\'][^>]*>.*?</style>',
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    tag = f'<style id="thecee-base">\n{css}\n</style>'
    if re.search(r'<style[\s>]', html, re.IGNORECASE):
        return re.sub(r'(<style[\s>])', tag + r'\n\1', html, count=1, flags=re.IGNORECASE)
    if re.search(r'</head\s*>', html, re.IGNORECASE):
        return re.sub(r'</head\s*>', tag + '</head>', html, count=1, flags=re.IGNORECASE)
    return tag + html


def _strip_base_style(html: str) -> str:
    return re.sub(
        r'<style\b[^>]*\bid=["\']thecee-base["\'][^>]*>.*?</style>\s*',
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
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


def _inject_enhancements(html: str) -> str:
    html = re.sub(
        r'<script\b[^>]*\bid=["\']thecee-fx["\'][^>]*>.*?</script>\s*',
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Clean scroll-triggered reveal animations — no gimmicks
    script = """<script id="thecee-fx">
document.addEventListener('DOMContentLoaded',function(){
  const observer=new IntersectionObserver(function(entries){
    entries.forEach(function(e){
      if(e.isIntersecting){e.target.style.opacity='1';e.target.style.transform='translateY(0)';observer.unobserve(e.target);}
    });
  },{threshold:0.1});
  document.querySelectorAll('section, .card, .page>div').forEach(function(el, i){
    if(!el.classList.contains('page')){el.style.opacity='0';el.style.transform='translateY(24px)';el.style.transition='opacity 0.6s ease-out, transform 0.6s ease-out';el.style.transitionDelay=(i*0.08)+'s';observer.observe(el);}
  });
});
</script>"""
    if re.search(r"</body\s*>", html, re.IGNORECASE):
        return re.sub(r"</body\s*>", script + "</body>", html, count=1, flags=re.IGNORECASE)
    return html + script


_UI_JS_BOILERPLATE = """<script id="thecee-app">
// ── TheCee Autonomous Runtime ─────────────────────────────
// Detects what elements exist in the DOM and wires them up.
// All selectors use safe optional chaining — no errors if absent.
(function(){
const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
const on=(el,ev,fn)=>el?.addEventListener(ev,fn);
var S={cart:[],navOpen:false};

// ── 1. Navigation: auto-detect pattern and wire up ──
// Priority: data-page divs > same-page anchors > smooth scroll
var hasSPA=$$('[data-page]').length>0;
if(hasSPA) $$('[data-page]').forEach(function(p,i){if(i>0)p.style.display='none';});
function navTo(name){
  if(hasSPA){
    $$('[data-page]').forEach(function(p){p.style.display='none';});
    var t=$('[data-page="'+name+'"]');
    if(t){t.style.display='block';window.scrollTo({top:0,behavior:'smooth'});}
  }else{
    var t=$('[id="'+name+'"]')||$('[data-section="'+name+'"]');
    if(t)t.scrollIntoView({behavior:'smooth'});
    else window.scrollTo({top:0,behavior:'smooth'});
  }
}

// ── 2. data-thecee-id click router (powers simulation + UX) ──
document.addEventListener('click',function(e){
  var el=e.target.closest('[data-thecee-id]');
  if(!el)return;
  var id=el.getAttribute('data-thecee-id');
  // Simulation logging
  console.log('TheCee:',id);
  // Navigation
  if(id==='nav-home')navTo('home');
  else if(id==='nav-products')navTo('product');
  else if(id==='nav-cart'){var cl=$('[data-page="cart"]');if(cl)navTo('cart');else if($('#cart-list')||$('.cart')){$('#cart-list,.cart')?.classList.toggle('hidden');}}
  else if(id==='cta-primary'){/* logged for simulation */}
});

// ── 3. Cart system (auto-detected) ──
function addToCart(name,price,qty){
  qty=qty||1;
  var ex=S.cart.find(function(i){return i.name===name;});
  if(ex)ex.qty+=qty;else S.cart.push({name:name,price:price,qty:qty});
  renderCart();showToast(name+' added!');
}
function removeFromCart(i){S.cart.splice(i,1);renderCart();}
function renderCart(){
  var badge=$('#cart-count');
  var count=S.cart.reduce(function(s,i){return s+i.qty;},0);
  if(badge){badge.textContent=count;badge.style.display=count?'':'none';}
  var list=$('#cart-list');
  if(!list)return;
  if(!S.cart.length){list.innerHTML='<div class="p-12 text-center opacity-60">Your cart is empty</div>';return;}
  list.innerHTML=S.cart.map(function(i,idx){
    return '<div class="flex items-center justify-between py-3 border-b"><div><div class="font-medium">'+i.name+'</div><div class="text-sm opacity-60">Qty: '+i.qty+'</div></div><button onclick="removeFromCart('+idx+')" class="text-red-500 hover:text-red-700 p-1">✕</button></div>';
  }).join('');
  var sub=S.cart.reduce(function(s,i){return s+i.price*i.qty;},0);
  ['cart-subtotal','cart-total'].forEach(function(id){var e=$('#'+id);if(e)e.textContent='₹'+sub.toLocaleString('en-IN');});
}
document.addEventListener('click',function(e){
  var el=e.target.closest('[data-thecee-id="add-to-cart"]');
  if(!el)return;
  var n=el.getAttribute('data-product-name')||'Product';
  var p=parseFloat(el.getAttribute('data-product-price'))||999;
  var q=parseInt(el.getAttribute('data-qty')||'1');
  addToCart(n,p,q);
});

// ── 4. Toast (auto-creates if missing) ──
function showToast(m){
  var t=$('#toast');
  if(!t){
    t=document.createElement('div');
    t.id='toast';
    t.style.cssText='position:fixed;bottom:24px;right:24px;background:#1f2937;color:white;padding:12px 24px;border-radius:8px;z-index:9999;opacity:0;transform:translateY(16px);transition:all 0.3s;font-size:14px;';
    document.body.appendChild(t);
  }
  t.textContent=m;
  t.style.opacity='1';t.style.transform='translateY(0)';
  clearTimeout(t._tid);t._tid=setTimeout(function(){t.style.opacity='0';t.style.transform='translateY(16px)';},3000);
}

// ── 5. Navbar scroll effect (auto-detected) ──
var nav=$('#main-nav')||$('nav');
if(nav&&!nav.id)nav.id='main-nav';
window.addEventListener('scroll',function(){
  var n=$('#main-nav');
  if(n)n.style.boxShadow=window.scrollY>10?'0 1px 3px rgba(0,0,0,0.1)':'none';
},{passive:true});

// ── 6. Mobile drawer (auto-detected) ──
var menuBtn=$('#menu-btn')||$('[aria-label="menu"]')||$('.menu-btn');
var drawer=$('#mobile-drawer');
var overlay=$('#drawer-overlay');
if(menuBtn&&drawer){
  on(menuBtn,'click',function(){
    S.navOpen=!S.navOpen;drawer.classList.toggle('open',S.navOpen);
    if(overlay){overlay.classList.toggle('open',S.navOpen);overlay.style.pointerEvents=S.navOpen?'auto':'none';}
  });
  if(overlay)on(overlay,'click',function(){S.navOpen=false;drawer.classList.remove('open');overlay.style.pointerEvents='none';});
}

// ── 7. Lucide icons ──
if(typeof lucide!=='undefined')try{lucide.createIcons();}catch(e){}

// ── 8. FAQ accordion (auto-detected) ──
$$('.faq-item').forEach(function(item,i){
  var btn=item.querySelector('.faq-q,.faq-question,button');
  var ans=item.querySelector('.faq-answer');
  if(!btn||!ans)return;
  on(btn,'click',function(){
    var isOpen=item.classList.contains('active');
    $$('.faq-item').forEach(function(x){x.classList.remove('active');});
    if(!isOpen)item.classList.add('active');
  });
});

// ── 9. Tabs (auto-detected) ──
$$('.tabs-container').forEach(function(container){
  var btns=container.querySelectorAll('.tab-btn');
  var panels=container.querySelectorAll('.tab-panel');
  if(!btns.length)return;
  btns.forEach(function(btn){
    on(btn,'click',function(){
      btns.forEach(function(b){b.classList.remove('active','border-primary','text-foreground');});
      btn.classList.add('active');
      var target=btn.getAttribute('data-tab-target');
      panels.forEach(function(p){
        p.style.display=p.getAttribute('data-tab-id')===target?'block':'none';
      });
    });
  });
});

// ── 10. Form submission (auto-detected) ──
document.addEventListener('submit',function(e){
  var form=e.target.closest('[data-thecee-id="checkout-form"]');
  if(!form)return;
  e.preventDefault();
  if(!S.cart.length)return showToast('Cart is empty');
  S.cart=[];renderCart();
  navTo('confirmation');
  showToast('Order placed!');
});

renderCart();
})();
</script>"""


def _inject_js_boilerplate(html: str) -> str:
    """Inject TheCee SPA JavaScript boilerplate before </body>.

    Kept server-side so Claude doesn't have to reproduce ~140 lines of JS
    every generation, making the prompt shorter and output more reliable.
    """
    if re.search(r'<script\b[^>]*\bid=["\']thecee-app["\']', html):
        return html
    if re.search(r"</body\s*>", html, re.IGNORECASE):
        return re.sub(r"</body\s*>", _UI_JS_BOILERPLATE + "</body>", html, count=1, flags=re.IGNORECASE)
    return html + _UI_JS_BOILERPLATE


def _build_safe_html(raw: str) -> str:
    """Coerce raw model output into a self-contained, valid prototype document.

    Pipeline:
      1. Coerce to a complete HTML document (handles fences, fragments, truncation).
      2. Strip non-allowlisted external scripts.
      3. Inject Tailwind CDN if missing.
      4. Guarantee the required tracking attributes exist.
      5. Inject scroll-reveal animations.
      6. Inject SPA JS boilerplate.
    """
    doc = _coerce_to_html_doc(raw)
    doc = _strip_unsafe_scripts(doc)
    doc = _ensure_cdns(doc)
    doc = _ensure_tracking_ids(doc)
    doc = _inject_enhancements(doc)
    doc = _inject_js_boilerplate(doc)
    is_valid, msg = validate_generated_html(doc)
    if not is_valid:
        logger.warning("[UI] Generated HTML validation: %s", msg)
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
    project = get_owned_project(db, current_user.id, project_id)

    layout_arch, layout_instruction = select_layout_archetype(body.product_type)
    prompt = UI_GENERATION_PROMPT.format(
        description=(project.description or "") + "\n\n" + body.prompt,
        product_type=body.product_type,
        target_segment=body.target_demographic or "general Indian consumer",
        price_point=body.price_point or "competitive",
        layout_archetype=layout_instruction,
    )

    out = claude_call_with_fallback(
        [{"role": "user", "content": prompt}],
        model="claude-sonnet-4-6",
        max_tokens=8192,
        fallback_key="ui_generation",
        timeout=240,
        system=UI_GENERATION_SYSTEM,
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

    _lock_project_for_ui_version(db, project_id, current_user.id)
    ui = GeneratedUI(
        project_id=project_id,
        prompt=body.prompt,
        html_content=html,
        version=_next_ui_version(db, project_id),
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
    project = get_owned_project(db, current_user.id, project_id)

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

    html_for_model = _strip_base_style(existing.html_content or "")
    refine_prompt = UI_REFINE_PROMPT_TEMPLATE.format(
        html=html_for_model,
        instruction=body.refinement_prompt,
    )

    out = claude_call_with_fallback(
        [{"role": "user", "content": refine_prompt}],
        model="claude-sonnet-4-6",
        max_tokens=16000,
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

    html = _build_safe_html(raw, css_template=css)

    _lock_project_for_ui_version(db, project_id, current_user.id)
    new_ui = GeneratedUI(
        project_id=project_id,
        prompt=body.refinement_prompt,
        html_content=html,
        version=_next_ui_version(db, project_id),
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
    project = get_owned_project(db, current_user.id, project_id)

    uis = (
        db.query(GeneratedUI)
        .filter(GeneratedUI.project_id == project_id)
        .order_by(GeneratedUI.id.desc())
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
    dependencies=[Depends(rate_limit(limit=20, window_s=60))],
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

    project = get_owned_project(db, current_user.id, project_id)

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
    project = get_owned_project(db, current_user.id, project_id)

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

    project = get_owned_project(db, current_user.id, project_id)

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

    project = get_owned_project(db, current_user.id, project_id)

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

    project = get_owned_project(db, current_user.id, project_id)

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

    conductor_results, cluster_list, product_type_str = _load_conductor_results(run)

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
    from app.simulation.retention_churn import RetentionChurnEngine

    project = get_owned_project(db, current_user.id, project_id)

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

    conductor_results, cluster_list, product_type_str = _load_conductor_results(run)

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
    from app.simulation.infra_scaling import InfraScalingEngine
    from app.simulation.retention_churn import RetentionChurnEngine

    project = get_owned_project(db, current_user.id, project_id)

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

    conductor_results, cluster_list, product_type_str = _load_conductor_results(run)

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

    project = get_owned_project(db, current_user.id, project_id)

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

    conductor_results, cluster_list, product_type_str = _load_conductor_results(run)

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

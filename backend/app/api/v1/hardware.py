from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.hardware.competitive_analysis import HardwareCompetitiveAnalyser
from app.hardware.manufacturing_cost import ManufacturingCostAnalyser
from app.reports.hardware_report import HardwareReportGenerator
from app.hardware.engineering_plate import compute_engineering_plate_labels
from app.hardware.model_generator import HardwareModelGenerator
from app.hardware.test_configs import TEST_DEFAULTS, TestConfigBuilder
from app.models.project import Project
from app.tasks.hardware_consumer_simulation import run_hardware_consumer_simulation
from app.tasks.hardware_tasks import run_hardware_tests
from app.models.project_hardware import Hardware3DModel, HardwareProduct
from app.models.user import User
from app.schemas.hardware import (
    VALID_PRODUCT_TYPES,
    HardwareGenerateSpecRequest,
    HardwareEngineeringPlateOut,
    HardwareGenerateSpecResponse,
    HardwareProductDetailResponse,
    HardwareProductListItem,
    HardwareRefineSpecRequest,
    HardwareRefineSpecResponse,
    HardwareRenderHintsOut,
)

router = APIRouter(tags=["hardware"])

_JSON_200 = {200: {"description": "Success", "content": {"application/json": {}}}}
_JSON_202 = {202: {"description": "Accepted", "content": {"application/json": {}}}}
_PDF_200 = {200: {"description": "PDF file", "content": {"application/pdf": {}}}}

_test_config_builder = TestConfigBuilder()
_cost_analyser = ManufacturingCostAnalyser()
_competitive_analyser = HardwareCompetitiveAnalyser()


def _get_owned_project(
    db: Session, project_id: int, user_id: int
) -> Project:
    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _normalize_dimensions_rough(
    value: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    s = str(value).strip()
    if not s:
        return None
    return {"notes": s}


def _estimate_polygon_count(spec: dict[str, Any]) -> int:
    comps = spec.get("components") or []
    total_vol = sum(float(c.get("volume_cm3", 0) or 0) for c in comps)
    est = int(total_vol * 80.0)
    return min(2_000_000, max(500, est))


def _spec_preview(spec: dict[str, Any]) -> str:
    name = str(spec.get("product_name", "Product"))
    ac = str(spec.get("assembly_complexity", ""))
    n = len(spec.get("components") or [])
    cat = str(spec.get("category", ""))
    parts = [f"{name}", f"{n} components"]
    if cat:
        parts.append(cat)
    if ac:
        parts.append(f"{ac} assembly")
    text = " — ".join(parts)
    return text[:500]


@router.post(
    "/projects/{project_id}/hardware/generate-spec",
    response_model=HardwareGenerateSpecResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a hardware semantic spec and 3D model JSON (Claude)",
)
def generate_hardware_spec(
    project_id: int,
    body: HardwareGenerateSpecRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.NVIDIA_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NVIDIA_API_KEY is not configured",
        )
    pt = body.product_type.strip().lower()
    if pt not in VALID_PRODUCT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid product_type; expected one of: "
                f"{', '.join(sorted(VALID_PRODUCT_TYPES))}"
            ),
        )

    _get_owned_project(db, project_id, current_user.id)

    dims_store = _normalize_dimensions_rough(body.dimensions_rough)

    try:
        gen = HardwareModelGenerator()
        spec = gen.generate_spec(
            description=body.description,
            category=body.category,
            price=body.target_price_inr,
            material_preference=body.material_preference,
            dimensions_rough=body.dimensions_rough,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    weight = spec.get("dimensions", {}).get("weight_grams")
    weight_f = float(weight) if isinstance(weight, (int, float)) else None

    material_spec_val = (body.material_preference or "").strip() or None

    product = HardwareProduct(
        project_id=project_id,
        name=body.name.strip(),
        description=body.description.strip(),
        category=body.category.strip(),
        product_type=pt,
        target_price_inr=float(body.target_price_inr),
        material_spec=material_spec_val,
        dimensions_json=dims_store,
        weight_grams=weight_f,
    )
    db.add(product)
    db.flush()

    model = Hardware3DModel(
        hardware_product_id=product.id,
        model_type="GENERATED",
        model_data_json=spec,
        polygon_count=_estimate_polygon_count(spec),
        generation_prompt=body.description.strip()[:8000],
    )
    db.add(model)
    db.commit()

    rh = HardwareRenderHintsOut.model_validate(spec["render_hints"])
    return HardwareGenerateSpecResponse(
        id=product.id,
        spec_preview=_spec_preview(spec),
        components=list(spec.get("components") or []),
        stress_points=list(spec.get("stress_point_map") or []),
        render_hints=rh,
    )


@router.post(
    "/projects/{project_id}/hardware/refine-spec",
    response_model=HardwareRefineSpecResponse,
    summary="Refine an existing hardware spec with a new instruction",
)
def refine_hardware_spec(
    project_id: int,
    body: HardwareRefineSpecRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.NVIDIA_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NVIDIA_API_KEY is not configured",
        )

    _get_owned_project(db, project_id, current_user.id)

    product = (
        db.query(HardwareProduct)
        .filter(
            HardwareProduct.id == body.hardware_product_id,
            HardwareProduct.project_id == project_id,
        )
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found for this project",
        )

    latest = (
        db.query(Hardware3DModel)
        .filter(Hardware3DModel.hardware_product_id == product.id)
        .order_by(desc(Hardware3DModel.created_at))
        .first()
    )
    if not latest or not latest.model_data_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existing spec to refine",
        )

    try:
        gen = HardwareModelGenerator()
        new_spec = gen.refine_spec(latest.model_data_json, body.refinement_prompt)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        ) from e

    new_model = Hardware3DModel(
        hardware_product_id=product.id,
        model_type="GENERATED",
        model_data_json=new_spec,
        polygon_count=_estimate_polygon_count(new_spec),
        generation_prompt=body.refinement_prompt.strip()[:8000],
    )
    db.add(new_model)

    w = new_spec.get("dimensions", {}).get("weight_grams")
    if isinstance(w, (int, float)):
        product.weight_grams = float(w)
    db.commit()
    db.refresh(new_model)

    return HardwareRefineSpecResponse(
        hardware_product_id=product.id,
        model_id=new_model.id,
        spec=new_spec,
    )


@router.get(
    "/projects/{project_id}/hardware",
    response_model=list[HardwareProductListItem],
    summary="List hardware products for a project",
)
def list_hardware_products(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    rows = (
        db.query(HardwareProduct)
        .filter(HardwareProduct.project_id == project_id)
        .order_by(desc(HardwareProduct.created_at))
        .all()
    )
    return [HardwareProductListItem.model_validate(r) for r in rows]


@router.get(
    "/projects/{project_id}/hardware/{hw_id}",
    response_model=HardwareProductDetailResponse,
    summary="Get hardware product and latest spec JSON",
)
def get_hardware_product(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    product = (
        db.query(HardwareProduct)
        .filter(
            HardwareProduct.id == hw_id,
            HardwareProduct.project_id == project_id,
        )
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    latest = (
        db.query(Hardware3DModel)
        .filter(Hardware3DModel.hardware_product_id == product.id)
        .order_by(desc(Hardware3DModel.created_at))
        .first()
    )
    if not latest or not latest.model_data_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No generated spec for this hardware product",
        )

    spec = latest.model_data_json
    rh = HardwareRenderHintsOut.model_validate(spec["render_hints"])

    return HardwareProductDetailResponse(
        id=product.id,
        project_id=product.project_id,
        name=product.name,
        description=product.description,
        category=product.category,
        product_type=product.product_type,
        target_price_inr=product.target_price_inr,
        material_spec=product.material_spec,
        dimensions_json=product.dimensions_json,
        weight_grams=product.weight_grams,
        created_at=product.created_at,
        spec=spec,
        render_hints=rh,
    )


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/engineering-plate",
    response_model=HardwareEngineeringPlateOut,
    summary="AI labels for engineering title block (project, category, components, mass, scale)",
)
def post_engineering_plate_labels(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    product = (
        db.query(HardwareProduct)
        .filter(
            HardwareProduct.id == hw_id,
            HardwareProduct.project_id == project_id,
        )
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )
    latest = (
        db.query(Hardware3DModel)
        .filter(Hardware3DModel.hardware_product_id == product.id)
        .order_by(desc(Hardware3DModel.created_at))
        .first()
    )
    if not latest or not latest.model_data_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No generated spec for this hardware product",
        )
    spec = latest.model_data_json
    if isinstance(spec, str):
        spec = json.loads(spec or "{}")
    spec = dict(spec)
    labels = compute_engineering_plate_labels(
        spec,
        product_name_fallback=product.name or "",
        category_fallback=(product.category or product.product_type or ""),
    )
    return HardwareEngineeringPlateOut.model_validate(labels)


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/run-tests",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue physics / structural hardware tests (Celery)",
    responses=_JSON_202,
)
def trigger_hardware_tests(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text(
            "SELECT id, name FROM hardware_products WHERE id=:id AND project_id=:pid"
        ),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    model = db.execute(
        text(
            "SELECT id FROM hardware_3d_models WHERE hardware_product_id=:hw_id LIMIT 1"
        ),
        {"hw_id": hw_id},
    ).fetchone()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate a hardware spec first before running tests",
        )

    task = run_hardware_tests.delay(
        hardware_product_id=hw_id,
        project_id=project_id,
    )

    return {
        "task_id": task.id,
        "status": "QUEUED",
        "message": f"Tests queued for {hw.name}. Check /test-results for output.",
        "hw_id": hw_id,
        "project_id": project_id,
    }


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/test-results",
    summary="Aggregated hardware test results and top failure points",
    responses=_JSON_200,
)
def get_test_results(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text(
            "SELECT id, name, category FROM hardware_products "
            "WHERE id=:id AND project_id=:pid"
        ),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    rows = db.execute(
        text("""
        SELECT id, test_type, status, results_json,
               failure_points_json, pass_rate, created_at
        FROM hardware_test_results
        WHERE hardware_product_id = :hw_id
        ORDER BY
          CASE status
            WHEN 'FAIL'    THEN 0
            WHEN 'PARTIAL' THEN 1
            WHEN 'PASS'    THEN 2
          END ASC,
          pass_rate ASC
    """),
        {"hw_id": hw_id},
    ).fetchall()

    results: list[dict[str, Any]] = []
    all_fp: list[dict] = []
    for r in rows:
        fp = (
            r.failure_points_json
            if isinstance(r.failure_points_json, list)
            else json.loads(r.failure_points_json or "[]")
        )
        metrics = (
            r.results_json
            if isinstance(r.results_json, dict)
            else json.loads(r.results_json or "{}")
        )

        severity = (
            "CRITICAL"
            if r.status == "FAIL"
            else ("WARNING" if r.status == "PARTIAL" else "INFO")
        )
        results.append(
            {
                "id": r.id,
                "test_type": r.test_type,
                "status": r.status,
                "pass_rate": r.pass_rate,
                "severity": severity,
                "metrics": metrics,
                "failure_points": fp,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
        all_fp.extend(fp)

    SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    all_fp.sort(key=lambda x: SEVERITY_ORDER.get(x.get("severity", "INFO"), 2))
    seen: set[str] = set()
    top3: list[dict] = []
    for fp in all_fp:
        cid = str(fp.get("component_id", ""))
        if cid not in seen:
            seen.add(cid)
            top3.append(fp)
        if len(top3) >= 3:
            break

    overall_pass = sum(r["pass_rate"] for r in results) / max(len(results), 1)

    return {
        "hardware_product_id": hw_id,
        "hardware_name": hw.name,
        "category": hw.category,
        "total_tests": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed": sum(1 for r in results if r["status"] == "FAIL"),
        "overall_pass_rate": round(overall_pass, 4),
        "top_failure_points": top3,
        "results": results,
    }


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/test-configs",
    summary="Create test configurations for a hardware product",
    responses=_JSON_200,
)
def create_test_configs(
    project_id: int,
    hw_id: int,
    body: Annotated[dict[str, Any], Body(...)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Body options:
      {"use_defaults": true}          → category defaults from product_type
      {"configs": [{test_type, ...}]} → custom configs
    """
    _get_owned_project(db, project_id, current_user.id)
    product = (
        db.query(HardwareProduct)
        .filter(
            HardwareProduct.id == hw_id,
            HardwareProduct.project_id == project_id,
        )
        .first()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    if body.get("use_defaults"):
        ptype = (product.product_type or "consumer_hardware").strip().lower()
        configs = _test_config_builder.defaults_for_category(ptype)
    elif isinstance(body.get("configs"), list):
        configs = []
        for c in body["configs"]:
            if not isinstance(c, dict) or "test_type" not in c:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each config must be an object with test_type",
                )
            try:
                cfg = _test_config_builder.custom_config(
                    test_type=str(c["test_type"]),
                    params=dict(c.get("parameters") or {}),
                    severity_weight=float(c.get("severity_weight", 0.5)),
                )
            except (ValueError, TypeError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                ) from e
            ok, err = _test_config_builder.validate_config(cfg)
            if not ok:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid config: {err}",
                )
            configs.append(cfg)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must include use_defaults: true or configs: [...]",
        )

    saved: list[dict[str, Any]] = []
    for cfg in configs:
        params_out = dict(cfg.parameters)
        params_out["severity_weight"] = cfg.severity_weight
        db.execute(
            text(
                """
                INSERT INTO hardware_test_configs
                    (hardware_product_id, test_type, parameters_json,
                     environment_conditions_json, created_at)
                VALUES
                    (:hw_id, :test_type, CAST(:params AS jsonb),
                     CAST(:env AS jsonb), NOW())
                """
            ),
            {
                "hw_id": hw_id,
                "test_type": cfg.test_type,
                "params": json.dumps(params_out),
                "env": json.dumps(cfg.environment),
            },
        )
        saved.append(_test_config_builder.to_dict(cfg))

    db.commit()
    return {"saved": len(saved), "configs": saved}


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/test-configs",
    summary="List saved test configurations",
    responses=_JSON_200,
)
def get_test_configs(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    exists = (
        db.query(HardwareProduct)
        .filter(
            HardwareProduct.id == hw_id,
            HardwareProduct.project_id == project_id,
        )
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    rows = (
        db.execute(
            text(
                """
                SELECT id, test_type, parameters_json,
                       environment_conditions_json, created_at
                FROM hardware_test_configs
                WHERE hardware_product_id = :hw_id
                ORDER BY created_at ASC
                """
            ),
            {"hw_id": hw_id},
        )
        .mappings()
        .all()
    )

    configs_out: list[dict[str, Any]] = []
    for r in rows:
        defaults = TEST_DEFAULTS.get(r["test_type"], {})
        pjson = r["parameters_json"]
        if isinstance(pjson, str):
            pjson = json.loads(pjson or "{}")
        elif pjson is None:
            pjson = {}
        ejson = r["environment_conditions_json"]
        if isinstance(ejson, str):
            ejson = json.loads(ejson or "{}")
        elif ejson is None:
            ejson = {}
        created = r["created_at"]
        configs_out.append(
            {
                "id": r["id"],
                "test_type": r["test_type"],
                "display_name": defaults.get("display_name", r["test_type"]),
                "description": defaults.get("description", ""),
                "parameters": pjson,
                "environment": ejson,
                "created_at": created.isoformat() if created is not None else None,
            }
        )

    return {
        "hardware_product_id": hw_id,
        "configs": configs_out,
        "total": len(configs_out),
    }


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/cost-analysis",
    summary="Run BOM and manufacturing cost estimate",
    responses=_JSON_200,
)
def run_cost_analysis(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    body: dict[str, Any] = Body(default_factory=dict),
):
    """
    Body: ``target_price_inr`` (optional), ``moq`` (optional, default 500).
    """
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text("""
        SELECT hp.id, hp.name, hp.category, hp.target_price_inr,
               hm.model_data_json
        FROM hardware_products hp
        LEFT JOIN hardware_3d_models hm
          ON hm.hardware_product_id = hp.id
        WHERE hp.id = :hw_id AND hp.project_id = :pid
        ORDER BY hm.created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id, "pid": project_id},
    ).fetchone()

    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )
    if not hw.model_data_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate a hardware spec first",
        )

    spec = (
        hw.model_data_json
        if isinstance(hw.model_data_json, dict)
        else json.loads(hw.model_data_json)
    )

    spec = dict(spec)
    spec["category"] = (hw.category or "consumer_hardware").strip().lower() or "consumer_hardware"

    target_price = float(body.get("target_price_inr", hw.target_price_inr or 1999))
    moq = int(body.get("moq", 500))

    estimate = _cost_analyser.estimate(spec, target_price, moq)
    result = estimate.to_dict()

    db.execute(
        text("""
        INSERT INTO hardware_manufacturing_estimates
        (hardware_product_id, bom_json, unit_cost_inr, tooling_cost_inr,
         moq, lead_time_days, margin_at_target_price, created_at)
        VALUES (:hw_id, CAST(:bom AS jsonb), :unit_cost, :tooling,
                :moq, :lead_time, :margin, NOW())
    """),
        {
            "hw_id": hw_id,
            "bom": json.dumps(result["bom"]),
            "unit_cost": result["landed_cost_inr"],
            "tooling": result["tooling_cost_inr"],
            "moq": moq,
            "lead_time": 45,
            "margin": result["margin_pct"],
        },
    )
    db.commit()

    return result


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/cost-analysis",
    summary="Get last manufacturing cost analysis row",
    responses=_JSON_200,
)
def get_cost_analysis(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text("SELECT id FROM hardware_products WHERE id=:id AND project_id=:pid"),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    row = db.execute(
        text("""
        SELECT bom_json, unit_cost_inr, tooling_cost_inr,
               moq, lead_time_days, margin_at_target_price, created_at
        FROM hardware_manufacturing_estimates
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id},
    ).fetchone()

    if not row:
        return {
            "message": "No cost analysis run yet. POST to /cost-analysis first.",
        }

    bom = row.bom_json
    if isinstance(bom, str):
        bom = json.loads(bom or "[]")
    elif bom is None:
        bom = []

    return {
        "hardware_product_id": hw_id,
        "bom": bom,
        "landed_cost_inr": row.unit_cost_inr,
        "tooling_cost_inr": row.tooling_cost_inr,
        "moq": row.moq,
        "lead_time_days": row.lead_time_days,
        "margin_pct": row.margin_at_target_price,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/consumer-simulation",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue 52-cluster consumer simulation for hardware (optional UI loop)",
    responses=_JSON_202,
)
def trigger_consumer_simulation(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    body: dict[str, Any] = Body(default_factory=dict),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text(
            "SELECT id, name FROM hardware_products WHERE id=:id AND project_id=:pid"
        ),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    model = db.execute(
        text(
            "SELECT id FROM hardware_3d_models WHERE hardware_product_id=:hw_id LIMIT 1"
        ),
        {"hw_id": hw_id},
    ).fetchone()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate a hardware spec first",
        )

    generated_ui_id = body.get("generated_ui_id")
    if generated_ui_id is not None:
        generated_ui_id = int(generated_ui_id)

    task = run_hardware_consumer_simulation.delay(
        hardware_product_id=hw_id,
        project_id=project_id,
        generated_ui_id=generated_ui_id,
    )

    return {
        "task_id": task.id,
        "status": "QUEUED",
        "prototype_wired": generated_ui_id is not None,
        "message": (
            f"Consumer simulation queued for {hw.name} "
            f"{'with prototype loop' if generated_ui_id else 'without prototype'}."
        ),
    }


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/consumer-simulation",
    summary="Get latest consumer simulation status and results",
    responses=_JSON_200,
)
def get_consumer_simulation_results(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text("SELECT id FROM hardware_products WHERE id=:id AND project_id=:pid"),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    row = db.execute(
        text("""
        SELECT status, agent_count, product_type,
               results_json, conductor_result_json,
               generated_ui_id, created_at, completed_at
        FROM hardware_consumer_simulation_runs
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id},
    ).fetchone()

    if not row:
        return {
            "message": "No consumer simulation run yet. POST to /consumer-simulation first.",
        }

    results = row.results_json
    if isinstance(results, str):
        results = json.loads(results or "{}")
    elif results is None:
        results = {}

    return {
        "hardware_product_id": hw_id,
        "status": row.status,
        "agent_count": row.agent_count,
        "product_type": row.product_type,
        "prototype_wired": row.generated_ui_id is not None,
        "overall_conversion_rate": results.get("overall_conversion_rate", 0),
        "champion_clusters": results.get("champion_clusters", []),
        "blocker_clusters": results.get("blocker_clusters", []),
        "primary_failure_domain": results.get("primary_failure_domain", "unknown"),
        "domain_findings": (results.get("domain_findings") or [])[:5],
        "cluster_results": results.get("cluster_results", {}),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.post(
    "/projects/{project_id}/hardware/{hw_id}/competitive-analysis",
    summary="Hardware competitive analysis from spec, cost, and sim clusters",
    responses=_JSON_200,
)
def run_competitive_analysis(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text("""
        SELECT hp.id, hp.name, hp.category, hp.target_price_inr,
               hm.model_data_json
        FROM hardware_products hp
        LEFT JOIN hardware_3d_models hm
          ON hm.hardware_product_id = hp.id
        WHERE hp.id = :hw_id AND hp.project_id = :pid
        ORDER BY hm.created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id, "pid": project_id},
    ).fetchone()

    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )
    if not hw.model_data_json:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generate a hardware spec first",
        )

    spec = (
        hw.model_data_json
        if isinstance(hw.model_data_json, dict)
        else json.loads(hw.model_data_json)
    )
    spec = dict(spec)
    spec["category"] = (hw.category or "consumer_hardware").strip().lower() or "consumer_hardware"

    cost_row = db.execute(
        text("""
        SELECT bom_json, unit_cost_inr, tooling_cost_inr, moq,
               margin_at_target_price
        FROM hardware_manufacturing_estimates
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id},
    ).fetchone()

    cost_estimate: dict[str, Any] = {
        "target_price_inr": float(hw.target_price_inr or 1999),
        "landed_cost_inr": float(cost_row.unit_cost_inr) if cost_row else 0.0,
        "margin_pct": float(cost_row.margin_at_target_price) if cost_row else 0.0,
    }

    sim_row = db.execute(
        text("""
        SELECT results_json FROM hardware_consumer_simulation_runs
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id},
    ).fetchone()

    cluster_results: dict[str, Any] = {}
    if sim_row:
        sim_data = sim_row.results_json
        if isinstance(sim_data, str):
            sim_data = json.loads(sim_data or "{}")
        elif sim_data is None:
            sim_data = {}
        cluster_results = sim_data.get("cluster_results") or {}

    if not cluster_results:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Run consumer simulation first — competitive analysis needs cluster results",
        )

    report = _competitive_analyser.analyse(spec, cost_estimate, cluster_results)
    return report.to_dict()


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/competitive-analysis",
    summary="Get placeholder / cached competitive analysis hints from last sim",
    responses=_JSON_200,
)
def get_competitive_analysis(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)
    hw = db.execute(
        text("SELECT id FROM hardware_products WHERE id=:id AND project_id=:pid"),
        {"id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    sim_row = db.execute(
        text("""
        SELECT results_json FROM hardware_consumer_simulation_runs
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """),
        {"hw_id": hw_id},
    ).fetchone()

    if not sim_row:
        return {
            "message": (
                "No consumer simulation run yet. "
                "POST to /consumer-simulation then /competitive-analysis."
            ),
        }

    sim_data = sim_row.results_json
    if isinstance(sim_data, str):
        sim_data = json.loads(sim_data or "{}")
    elif sim_data is None:
        sim_data = {}

    cr = sim_data.get("cluster_results") or {}
    return {
        "message": "Re-run POST /competitive-analysis for fresh analysis",
        "cluster_count": len(cr),
        "overall_conv": sim_data.get("overall_conversion_rate", 0),
        "champion_clusters": sim_data.get("champion_clusters", []),
        "blocker_clusters": sim_data.get("blocker_clusters", []),
    }


@router.get(
    "/projects/{project_id}/hardware/{hw_id}/report.pdf",
    summary="Download hardware dossier PDF report",
    responses=_PDF_200,
)
def get_hardware_report_pdf(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_owned_project(db, project_id, current_user.id)

    hw = db.execute(
        text(
            """
        SELECT hp.id, hp.name, hp.category, hp.product_type,
               hp.target_price_inr,
               hm.model_data_json
        FROM hardware_products hp
        LEFT JOIN hardware_3d_models hm
          ON hm.hardware_product_id = hp.id
        WHERE hp.id = :hw_id AND hp.project_id = :pid
        ORDER BY hm.created_at DESC NULLS LAST LIMIT 1
    """
        ),
        {"hw_id": hw_id, "pid": project_id},
    ).fetchone()
    if not hw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hardware product not found",
        )

    spec = (
        hw.model_data_json
        if isinstance(hw.model_data_json, dict)
        else json.loads(hw.model_data_json or "{}")
    )
    spec = dict(spec)
    spec["category"] = (hw.category or "consumer_hardware").strip().lower() or "consumer_hardware"

    test_rows_all = db.execute(
        text(
            """
        SELECT test_type, status, results_json, failure_points_json, pass_rate, created_at
        FROM hardware_test_results
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC
    """
        ),
        {"hw_id": hw_id},
    ).fetchall()

    by_type: dict[str, Any] = {}
    for r in test_rows_all:
        tt = r.test_type
        if tt not in by_type:
            by_type[tt] = r

    test_results: list[dict[str, Any]] = []
    for r in by_type.values():
        test_results.append(
            {
                "test_type": r.test_type,
                "status": r.status,
                "pass_rate": r.pass_rate,
                "metrics": r.results_json
                if isinstance(r.results_json, dict)
                else json.loads(r.results_json or "{}"),
                "failure_points": r.failure_points_json
                if isinstance(r.failure_points_json, list)
                else json.loads(r.failure_points_json or "[]"),
            }
        )

    cost_row = db.execute(
        text(
            """
        SELECT bom_json, unit_cost_inr, tooling_cost_inr, moq,
               lead_time_days, margin_at_target_price
        FROM hardware_manufacturing_estimates
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """
        ),
        {"hw_id": hw_id},
    ).fetchone()

    target_price = float(hw.target_price_inr or 1999)
    moq = int(cost_row.moq) if cost_row and cost_row.moq else 500
    estimate = _cost_analyser.estimate(spec, target_price, moq)
    cost_estimate = estimate.to_dict()

    if cost_row:
        landed = float(cost_row.unit_cost_inr or 0)
        m = float(cost_row.margin_at_target_price or 0)
        cost_estimate["landed_cost_inr"] = landed
        cost_estimate["margin_pct"] = m
        cost_estimate["margin_inr"] = max(0.0, target_price - landed)
        bom_raw = cost_row.bom_json
        if isinstance(bom_raw, str):
            bom_list = json.loads(bom_raw or "[]")
        elif isinstance(bom_raw, list):
            bom_list = bom_raw
        else:
            bom_list = []
        if bom_list:
            cost_estimate["bom"] = bom_list
            cost_estimate["bom_total_inr"] = sum(
                float(b.get("unit_cost_inr", 0) or 0) for b in bom_list
            )
        tc = float(cost_row.tooling_cost_inr or 0)
        cost_estimate["tooling_cost_inr"] = tc
        cost_estimate["tooling_per_unit_inr"] = tc / max(moq, 1)
        cost_estimate["verdict"] = (
            "VIABLE" if m >= 35 else "MARGINAL" if m >= 20 else "NOT_VIABLE"
        )
        cost_estimate["verdict_reason"] = f"Margin {m:.1f}% (persisted manufacturing estimate)"

    sim_row = db.execute(
        text(
            """
        SELECT status, agent_count, results_json, generated_ui_id
        FROM hardware_consumer_simulation_runs
        WHERE hardware_product_id = :hw_id
        ORDER BY created_at DESC LIMIT 1
    """
        ),
        {"hw_id": hw_id},
    ).fetchone()

    consumer_sim: dict[str, Any] = {}
    if sim_row:
        consumer_sim = (
            sim_row.results_json
            if isinstance(sim_row.results_json, dict)
            else json.loads(sim_row.results_json or "{}")
        )
        consumer_sim["prototype_wired"] = sim_row.generated_ui_id is not None

    competitive: dict[str, Any] = {}
    try:
        cr = consumer_sim.get("cluster_results")
        if isinstance(cr, dict) and cr and cost_estimate:
            competitive = _competitive_analyser.analyse(spec, cost_estimate, cr).to_dict()
    except Exception:
        competitive = {}

    hardware_product_dict = {
        "name": hw.name,
        "category": hw.category,
        "product_type": hw.product_type,
        "target_price_inr": hw.target_price_inr,
    }

    gen = HardwareReportGenerator()
    pdf_bytes = gen.generate(
        hardware_product=hardware_product_dict,
        spec=spec,
        test_results=test_results,
        cost_estimate=cost_estimate,
        consumer_sim=consumer_sim,
        competitive=competitive,
        project_name=hw.name or "Hardware Product",
    )

    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=thecee-hardware-{hw_id}.pdf",
        },
    )

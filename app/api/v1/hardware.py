from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import desc, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.hardware.model_generator import HardwareModelGenerator
from app.hardware.test_configs import TEST_DEFAULTS, TestConfigBuilder
from app.models.project import Project
from app.tasks.hardware_tasks import run_hardware_tests
from app.models.project_hardware import Hardware3DModel, HardwareProduct
from app.models.user import User
from app.schemas.hardware import (
    VALID_PRODUCT_TYPES,
    HardwareGenerateSpecRequest,
    HardwareGenerateSpecResponse,
    HardwareProductDetailResponse,
    HardwareProductListItem,
    HardwareRefineSpecRequest,
    HardwareRefineSpecResponse,
    HardwareRenderHintsOut,
)

router = APIRouter(tags=["hardware"])
_test_config_builder = TestConfigBuilder()


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
)
def generate_hardware_spec(
    project_id: int,
    body: HardwareGenerateSpecRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured",
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
)
def refine_hardware_spec(
    project_id: int,
    body: HardwareRefineSpecRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY is not configured",
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
    "/projects/{project_id}/hardware/{hw_id}/run-tests",
    status_code=status.HTTP_202_ACCEPTED,
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


@router.get("/projects/{project_id}/hardware/{hw_id}/test-results")
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


@router.post("/projects/{project_id}/hardware/{hw_id}/test-configs")
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


@router.get("/projects/{project_id}/hardware/{hw_id}/test-configs")
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

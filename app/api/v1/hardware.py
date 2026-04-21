from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.hardware.model_generator import HardwareModelGenerator
from app.models.project import Project
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
def queue_hardware_run_tests(
    project_id: int,
    hw_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Step 72 UI — queue hardware test orchestration (Step 76 will wire Celery + DB).
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
    return {
        "status": "QUEUED",
        "hardware_product_id": hw_id,
        "project_id": project_id,
        "message": "Hardware test orchestration (Step 76) will attach to this endpoint.",
    }

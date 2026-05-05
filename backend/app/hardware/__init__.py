from __future__ import annotations

from typing import TYPE_CHECKING

from app.hardware.materials import (
    MATERIAL_DATABASE,
    MaterialSpec,
    estimate_component_cost,
    get_material,
    get_material_color,
    materials_for_category,
    resolve_material_name,
)

if TYPE_CHECKING:
    from app.hardware.model_generator import HardwareModelGenerator

__all__ = [
    "HardwareModelGenerator",
    "MATERIAL_DATABASE",
    "MaterialSpec",
    "estimate_component_cost",
    "get_material",
    "get_material_color",
    "materials_for_category",
    "resolve_material_name",
]


def __getattr__(name: str):
    if name == "HardwareModelGenerator":
        from app.hardware.model_generator import HardwareModelGenerator as _HMG

        return _HMG
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

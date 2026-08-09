"""Pydantic schemas for the architect-stack registry endpoint.

The conductor keeps the deterministic per-product-type architect stacks as
private internals (``ARCHITECT_STACKS`` / ``_ARCHITECTS``). This schema
exposes that metadata through the API so founders and operators can see which
domain-specialist architects actually run for a product type, which
architects are universal, and where a stack has coverage gaps.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ArchitectStackEntryOut(BaseModel):
    """One registered architect and its activation metadata."""

    name: str
    product_types: list[str] = Field(
        default_factory=list,
        description=(
            "Product types the architect declares as its activation filter. "
            "Empty means the architect applies to all product types."
        ),
    )
    universal: bool = Field(
        default=False,
        description="True when ``product_types`` is empty (BaseArchitect contract).",
    )
    stack_count: int = Field(
        default=0,
        description="How many product-type stacks include this architect.",
    )
    stacked_product_types: list[str] = Field(
        default_factory=list,
        description="Sorted product types whose stack includes this architect.",
    )
    active_for_product_type: bool | None = Field(
        default=None,
        description=(
            "Only populated when ``product_type`` is requested: whether the "
            "architect is part of that product type's stack."
        ),
    )
    stack_position: int | None = Field(
        default=None,
        description=(
            "1-based position in the requested product type's evaluation "
            "order; ``None`` when inactive or when no filter is supplied."
        ),
    )


class ProductTypeStackCoverageOut(BaseModel):
    """Per-product-type coverage summary."""

    product_type: str
    stack_size: int = 0
    universal_count: int = 0
    specialized_count: int = 0
    missing_count: int = 0


class ArchitectStackRegistryOut(BaseModel):
    """Response from ``GET /simulations/architect-stack``."""

    generated_at: datetime
    product_type: str | None = Field(
        default=None,
        description="Echoed filter; ``None`` when the full registry is returned.",
    )
    total_architects: int = 0
    stack_size: int | None = Field(
        default=None,
        description="Stack size for the requested product type; ``None`` without a filter.",
    )
    universal_count: int = 0
    specialized_count: int = 0
    missing_count: int = Field(
        default=0,
        description=(
            "Stack entries that reference an architect absent from the live "
            "registry. With a product-type filter this is that stack's gap; "
            "without one it is the gap summed across every stack."
        ),
    )
    architects: list[ArchitectStackEntryOut] = Field(default_factory=list)
    product_coverage: list[ProductTypeStackCoverageOut] = Field(default_factory=list)


__all__ = [
    "ArchitectStackEntryOut",
    "ArchitectStackRegistryOut",
    "ProductTypeStackCoverageOut",
]

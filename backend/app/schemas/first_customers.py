"""
Pydantic schemas for the first-customer trajectory insight.

``GET /api/v1/simulations/{id}/first-customers`` answers the founder
question the market-sizing digest intentionally leaves open: "assuming I
can get a steady stream of visitors, when do I land my first 10 / 100 /
1,000 customers, and which consumer clusters arrive first?"

The digest combines the simulation's population-weighted conversion
with a founder-supplied ``monthly_visitors`` expectation (linear
adoption model), emits milestone timing plus a 12-month adoption curve,
and ranks the clusters whose weighted conversion contributes the most
first customers.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FirstCustomerMilestone(BaseModel):
    """Timing + visitor requirement for one customer milestone."""

    milestone: int = 0
    months: float | None = None
    weeks: float | None = None
    visitors_needed: int | None = None
    display: str = ""


class AdoptionCurvePoint(BaseModel):
    """Projected cumulative customers at one month of the curve."""

    month: int = 0
    customers: int = 0


class FirstCustomerSegment(BaseModel):
    """One cluster's contribution to the first wave of customers."""

    cluster_id: str = ""
    cluster_name: str = ""
    population_weight: float = 0.0
    conversion_rate: float = 0.0
    first_adopter_share: float = 0.0


class FirstCustomersSignal(BaseModel):
    """One traffic-light signal for the first-customer digest."""

    key: str = ""
    label: str = ""
    level: str = "watch"  # ok | watch | critical
    message: str = ""


class FirstCustomersOut(BaseModel):
    """Full first-customer trajectory for a completed simulation."""

    simulation_id: int
    project_id: int
    status: str = "COMPLETED"
    weighted_conversion_rate: float = 0.0
    monthly_visitors: int = 0
    monthly_customers: float = 0.0
    milestones: list[FirstCustomerMilestone] = Field(default_factory=list)
    adoption_curve: list[AdoptionCurvePoint] = Field(default_factory=list)
    top_segments: list[FirstCustomerSegment] = Field(default_factory=list)
    signals: list[FirstCustomersSignal] = Field(default_factory=list)
    narrative: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AdoptionCurvePoint",
    "FirstCustomerMilestone",
    "FirstCustomerSegment",
    "FirstCustomersOut",
    "FirstCustomersSignal",
]

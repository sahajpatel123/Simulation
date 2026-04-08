from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class EnvironmentMode(str, Enum):
    MANUAL = "MANUAL"
    SCENARIO = "SCENARIO"
    TREND = "TREND"


class ScenarioType(str, Enum):
    EARLY_ADOPTER = "EARLY_ADOPTER"
    SATURATED = "SATURATED"
    RECESSION = "RECESSION"
    HIGH_GROWTH = "HIGH_GROWTH"
    VIRAL_LAUNCH = "VIRAL_LAUNCH"


class ManualParams(BaseModel):
    consumer_volume: int = Field(default=10000, ge=100, le=100000)
    growth_rate_per_month: float = Field(default=5.0, ge=-100.0, le=200.0)
    average_order_value: float = Field(default=999.0, ge=1.0, le=1000000.0)
    price_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    market_maturity: float = Field(default=0.3, ge=0.0, le=1.0)


SCENARIO_PRESETS: dict[str, ManualParams] = {
    "EARLY_ADOPTER": ManualParams(
        consumer_volume=5000,
        growth_rate_per_month=18.0,
        average_order_value=1499.0,
        price_sensitivity=0.2,
        market_maturity=0.05,
    ),
    "SATURATED": ManualParams(
        consumer_volume=50000,
        growth_rate_per_month=1.5,
        average_order_value=599.0,
        price_sensitivity=0.85,
        market_maturity=0.95,
    ),
    "RECESSION": ManualParams(
        consumer_volume=8000,
        growth_rate_per_month=-2.0,
        average_order_value=299.0,
        price_sensitivity=0.92,
        market_maturity=0.7,
    ),
    "HIGH_GROWTH": ManualParams(
        consumer_volume=20000,
        growth_rate_per_month=35.0,
        average_order_value=1299.0,
        price_sensitivity=0.3,
        market_maturity=0.2,
    ),
    "VIRAL_LAUNCH": ManualParams(
        consumer_volume=100000,
        growth_rate_per_month=80.0,
        average_order_value=499.0,
        price_sensitivity=0.15,
        market_maturity=0.1,
    ),
}


class EnvironmentCreate(BaseModel):
    mode: EnvironmentMode = EnvironmentMode.MANUAL
    manual_params: ManualParams | None = None
    scenario_type: ScenarioType | None = None

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> "EnvironmentCreate":
        if self.mode == EnvironmentMode.MANUAL and self.manual_params is None:
            self.manual_params = ManualParams()
        if self.mode == EnvironmentMode.SCENARIO and self.scenario_type is None:
            raise ValueError("scenario_type is required when mode is SCENARIO")
        return self


class EnvironmentOut(BaseModel):
    id: int
    project_id: int
    mode: str
    consumer_volume: int
    growth_rate_per_month: float
    average_order_value: float
    price_sensitivity: float
    market_maturity: float
    scenario_type: str | None
    manual_params_json: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EnvironmentSummary(BaseModel):
    id: int
    project_id: int
    mode: str
    consumer_volume: int
    is_configured: bool = True

    model_config = {"from_attributes": True}

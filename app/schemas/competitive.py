from pydantic import BaseModel, field_validator


class Competitor(BaseModel):
    name: str
    category: str
    features: list[str]
    pricing: str
    positioning: str
    target_segment: str
    strengths: list[str]
    weaknesses: list[str]
    india_presence: str
    threat_level: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        valid = {"DIRECT", "INDIRECT", "SUBSTITUTE"}
        normalized = value.upper().strip()
        return normalized if normalized in valid else "DIRECT"

    @field_validator("threat_level")
    @classmethod
    def validate_threat(cls, value: str) -> str:
        valid = {"HIGH", "MEDIUM", "LOW"}
        normalized = value.upper().strip()
        return normalized if normalized in valid else "MEDIUM"

    @field_validator("india_presence")
    @classmethod
    def validate_presence(cls, value: str) -> str:
        valid = {"STRONG", "MODERATE", "WEAK", "NONE"}
        normalized = value.upper().strip()
        return normalized if normalized in valid else "MODERATE"


class GapAnalysis(BaseModel):
    our_wins: list[str]
    our_losses: list[str]
    underserved_segments: list[str]
    key_differentiators: list[str]
    recommended_counter_moves: list[str]


class MarketMap(BaseModel):
    most_dangerous_competitor: str
    easiest_to_displace: str
    most_similar_to_us: str


VALID_POSITIONS = {"DOMINANT", "STRONG", "MODERATE", "CHALLENGING", "HIGH_RISK"}


class CompetitiveAnalysisOut(BaseModel):
    project_id: int
    competitors: list[Competitor]
    gap_analysis: GapAnalysis
    market_map: MarketMap
    overall_competitive_position: str
    position_rationale: str
    direct_competitor_count: int
    high_threat_count: int
    generated_at: str
    message: str = "Competitive analysis completed"


class CompetitiveAnalysisRequest(BaseModel):
    description_override: str | None = None
    target_market: str | None = None

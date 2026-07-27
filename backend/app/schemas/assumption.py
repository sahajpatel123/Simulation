from pydantic import BaseModel, Field


class AssumptionExtractRequest(BaseModel):
    description: str | None = Field(default=None, max_length=5000)


class AssumptionOut(BaseModel):
    id: int
    text: str
    category: str | None
    sensitivity: str
    impact_score: float
    is_hidden: bool

    model_config = {"from_attributes": True}


class AssumptionListResponse(BaseModel):
    project_id: int
    assumptions: list[AssumptionOut]
    total: int
    hidden_count: int
    message: str = "Assumptions extracted successfully"
    signal_quality: float | None = None
    signal_quality_tier: str | None = None
    claim_confidence_distribution: dict | None = None
    soft_contradiction_flags: list[str] = []


class AssumptionDigestOut(BaseModel):
    """Response from ``GET /projects/{id}/assumption-digest``.

    Per-project digest of AI-extracted assumptions so the
    dashboard's project-overview tile can answer "what does
    TheCee actually assume about my project, and which are
    the weakest links?" in a single API call.

    * ``assumption_count`` — non-hidden assumption count.
    * ``sensitivity_breakdown`` — ``{LOW/MEDIUM/HIGH/CRITICAL: count}``.
    * ``category_breakdown`` — ``{category: count}`` for the
      architect categories that produced the most claims.
    * ``high_impact_count`` — count of HIGH/CRITICAL-sensitivity
      assumptions.
    * ``weak_link_count`` — count of HIGH/CRITICAL
      assumptions whose specificity_score is below
      :data:`SPECIFICITY_WEAK_THRESHOLD`.
    * ``weak_links`` — capped (5) list of weak-link dicts
      ``{id, text, sensitivity, specificity_score,
      impact_score, category}``, sorted CRITICAL-first
      then by impact DESC.
    * ``recent_assumptions`` — capped (5) newest
      non-hidden assumptions.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    assumption_count: int = 0
    sensitivity_breakdown: dict[str, int] = {}
    category_breakdown: dict[str, int] = {}
    high_impact_count: int = 0
    weak_link_count: int = 0
    weak_links: list[dict] = []
    recent_assumptions: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []

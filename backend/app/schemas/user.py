from pydantic import BaseModel, EmailStr


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    tier: str

    model_config = {"from_attributes": True}


class UserDashboardOut(BaseModel):
    """Response from ``GET /me/dashboard``.

    One-shot account snapshot so the Account page can render
    a snapshot without fanning out to multiple endpoints.

    * ``account_age_days`` — days since signup.
    * ``account_age_label`` — human-friendly bucket.
    * ``tier`` — subscription tier label.
    * ``monthly_usage`` — ``{used, cap, remaining}`` for
      simulations this calendar month.
    * ``project_count`` / ``simulation_count`` /
      ``decision_count`` / ``outcome_count`` — totals.
    * ``last_activity_at`` — ISO timestamp of the user's
      most recent event (any source).
    * ``calibration_health`` — pass-through output of
      :func:`build_calibration_health` (or ``None``).
    * ``blindspot_count`` — recent-window blindspots.
    * ``narrative`` — one paragraph summary.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    account_age_days: int = 0
    account_age_label: str = ""
    tier: str = "FREE"
    monthly_usage: dict = {}
    project_count: int = 0
    simulation_count: int = 0
    decision_count: int = 0
    outcome_count: int = 0
    last_activity_at: str | None = None
    calibration_health: dict | None = None
    blindspot_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


    health_score: int = 0
    verdict: str = "AT_RISK"
    score_breakdown: dict[str, int] = {}
    narrative: str = ""
    key_signals: list[dict] = []


class CoverageGapsOut(BaseModel):
    """Response from ``GET /me/coverage-gaps``.

    Inverse of the portfolio-narrative: surfaces
    dimensions the user has NEVER explored so the
    dashboard can nudge them to broaden their input set.

    * ``covered_categories`` — sorted list of
      ``Assumption.category`` values present.
    * ``missing_categories`` — sorted list of standard
      categories the user has zero coverage on.
    * ``sensitivity_breakdown`` — ``{HIGH/...: count}``
      so the tile can render a "you have no HIGH/CRITICAL
      flagged" warning.
    * ``covered_cluster_count`` — distinct clusters
      touched across sims.
    * ``missing_architect_count`` — proxy: count of
      standard categories the user has no assumptions
      in.
    * ``total_assumption_count`` — total non-hidden.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    covered_categories: list[str] = []
    missing_categories: list[str] = []
    sensitivity_breakdown: dict[str, int] = {}
    covered_cluster_count: int = 0
    missing_architect_count: int = 0
    total_assumption_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


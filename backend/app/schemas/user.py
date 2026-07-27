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


    covered_categories: list[str] = []
    missing_categories: list[str] = []
    sensitivity_breakdown: dict[str, int] = {}
    covered_cluster_count: int = 0
    missing_architect_count: int = 0
    total_assumption_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class NotificationOut(BaseModel):
    """One inbox notification."""

    category: str = ""
    title: str = ""
    summary: str = ""
    severity: str = "info"
    occurred_at: str = ""
    ref_kind: str = ""
    ref_id: int | None = None
    ref_label: str | None = None


class NotificationsOut(BaseModel):
    """Response from ``GET /me/notifications``.

    Single-payload inbox view: a chronological (newest-
    first) list of items that would trigger an inbox or
    push notification for the founder, composed from
    blindspots, intervention quick wins, pending
    decisions, and recent premortem criticals.

    * ``notification_count`` — total items in the
      capped feed.
    * ``notifications`` — capped (25) list of
      :class:`NotificationOut` dicts.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    notification_count: int = 0
    notifications: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class WeeklyDigestOut(BaseModel):
    """Response from ``GET /me/weekly-digest``.

    One-shot "what happened in my account this week?"
    payload - rolling 7-day counts (sims, decisions,
    outcomes, completed sims) + last-week calibration
    health + cross-project rollups (quick wins, CRITICAL
    failure modes).

    Different from /me/dashboard (count snapshot) -
    this is the rolling-7d activity summary, useful as
    the preview content for the weekly email.

    * ``sim_count_week`` - sims created in last 7d.
    * ``decision_count_week`` - decisions enqueued in last 7d.
    * ``outcome_count_week`` - outcomes submitted in last 7d.
    * ``completed_sim_count_week`` - subset reached COMPLETED.
    * ``calibration_health`` - pass-through build_calibration_health
      for the rolling 7d window.
    * ``quick_wins_total`` - LOW-difficulty + priority > 0.70
      interventions across projects.
    * ``critical_failure_modes_total`` - CRITICAL premortem
      failure modes across projects.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity, display}``
      dicts for the dashboard tiles.
    """

    sim_count_week: int = 0
    decision_count_week: int = 0
    outcome_count_week: int = 0
    completed_sim_count_week: int = 0
    calibration_health: dict | None = None
    quick_wins_total: int = 0
    critical_failure_modes_total: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class DigestSnapshotOut(BaseModel):
    """Response from ``GET /me/digest-snapshot``.

    One-shot capture of every user-level endpoint into a
    single payload so the founder (or the system) can
    archive it for later comparison, or send it as a
    single email.

    Composes the 5 user-level digests:
    - ``dashboard`` - count snapshot
    - ``account_health`` - 0-100 health score
    - ``coverage_gaps`` - missing dimensions
    - ``notifications`` - inbox feed
    - ``weekly_digest`` - rolling-7d recap
    """

    snapshot_at: str = ""
    schema_version: int = 1
    dashboard: dict = {}
    account_health: dict = {}
    coverage_gaps: dict = {}
    notifications: dict = {}
    weekly_digest: dict = {}


class ProjectSummaryCard(BaseModel):
    """One row in /me/projects-summary."""

    id: int | None = None
    title: str | None = None
    status: str = "UNKNOWN"
    brief_completed: bool = False
    latest_sim_conversion_rate: float | None = None
    latest_sim_status: str | None = None
    latest_sim_created_at: str | None = None
    sim_count: int = 0
    decision_count: int = 0
    outcome_count: int = 0


class ProjectsSummaryOut(BaseModel):
    """Response from ``GET /me/projects-summary``.

    Lightweight per-project summary cards for the
    dashboard's projects-list grid view. Avoids sending
    full ProjectOut payloads (descriptions, tags, briefs)
    when only a few fields per project are needed.

    * ``project_count`` - total cards returned (capped).
    * ``projects`` - capped (50) list of
      :class:`ProjectSummaryCard` dicts.
    * ``sim_count_total`` / ``decision_count_total`` /
      ``outcome_count_total`` - portfolio rollups.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    project_count: int = 0
    projects: list[dict] = []
    sim_count_total: int = 0
    decision_count_total: int = 0
    outcome_count_total: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class UsageByWeekOut(BaseModel):
    """Response from ``GET /me/usage-by-week``.

    Weekly volume history for the last 12 weeks so the
    dashboard's 'usage over time' chart can render a
    single payload.

    * ``week_count`` - total weeks returned (capped at 12).
    * ``weeks`` - capped list of
      ``{week_start, sim_count, decision_count, outcome_count}``.
    * ``sim_total`` / ``decision_total`` / ``outcome_total``
      - portfolio rollups.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    week_count: int = 0
    sim_total: int = 0
    decision_total: int = 0
    outcome_total: int = 0
    weeks: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class ProjectsByStatusOut(BaseModel):
    """Response from ``GET /me/projects-by-status``.

    Tiny status-bucket count summary for the dashboard's
    projects-by-status pie chart.

    * ``project_count`` - total projects owned.
    * ``status_breakdown`` - ``{status: count}`` sorted by
      the most-common first.
    * ``most_common_status`` - the single most common
      status, useful for the pie chart's center label.
    * ``actionable_count`` - count of projects in PENDING
      or RUNNING status.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - severity-tagged display dicts.
    """

    project_count: int = 0
    status_breakdown: dict[str, int] = {}
    most_common_status: str | None = None
    actionable_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class TagTaxonomyOut(BaseModel):
    """Response from ``GET /me/tag-taxonomy``.

    Tag + project_count map for the dashboard's
    tag-filter dropdowns. Composes the user's distinct
    tags with how many projects each is on, sorted by
    project_count DESC then alphabetically.

    * ``tag_count`` - total distinct tags in use.
    * ``tags`` - sorted list of ``{tag, project_count}``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    tag_count: int = 0
    tags: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class MostActiveProjectOut(BaseModel):
    """Response from ``GET /me/most-active-project``.

    Single "where should I focus?" recommendation: the
    project with the most total activity (sims + decisions
    + outcomes) in the last 7 days.

    * ``has_activity`` - ``True`` when at least one project
      had >= 1 action in the window.
    * ``project_id`` / ``project_title`` - the winning
      project (or ``None``).
    * ``total_actions_7d`` - count of (sim + decision +
      outcome) for the winner.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    has_activity: bool = False
    project_id: int | None = None
    project_title: str | None = None
    total_actions_7d: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class QuickStatsOut(BaseModel):
    """Response from ``GET /me/quick-stats``.

    Minimal "one-liner" account summary for mobile
    widgets + sidebars. Different from /me/dashboard
    (verbose) — this is intentionally small so it can
    be embedded in a tight UI surface.

    * ``total_projects`` / ``total_simulations`` /
      ``total_decisions`` / ``total_outcomes`` -
      portfolio rollups.
    * ``account_age_days`` - days since signup.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    total_projects: int = 0
    total_simulations: int = 0
    total_decisions: int = 0
    total_outcomes: int = 0
    account_age_days: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class PortfolioHealthSnapshotOut(BaseModel):
    """Response from ``GET /me/portfolio-health-snapshot``.

    Single 0-100 portfolio health rollup across all of
    the user's projects, so the dashboard header can
    surface one big number without fanning out to every
    per-project /projects/{id}/health endpoint.

    * ``project_count`` - projects included in the
      rollup (excludes zero-score entries that look
      like missing data).
    * ``portfolio_health_score`` - average project
      health score (0-100).
    * ``verdict`` - ``HEALTHY`` (>= 70) /
      ``NEEDS_ATTENTION`` (41-69) / ``AT_RISK`` (<= 40).
    * ``average_score`` - same as
      ``portfolio_health_score`` but as a float
      (no rounding).
    * ``lowest_project_score`` - min score across the
      portfolio (or ``None`` when empty).
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    project_count: int = 0
    portfolio_health_score: int = 0
    verdict: str = "AT_RISK"
    average_score: float = 0.0
    lowest_project_score: int | None = None
    narrative: str = ""
    key_signals: list[dict] = []


class LastTouchedProjectOut(BaseModel):
    """Response from ``GET /me/last-touched-project``.

    Single "where was I last?" payload so the dashboard
    can return the user to their most recently active
    project with a single click.

    * ``has_activity`` - ``True`` when at least one
      activity row exists.
    * ``project_id`` / ``project_title`` - the winning
      project (or ``None``).
    * ``last_activity_at`` - ISO timestamp of the most
      recent activity (or ``None``).
    * ``last_activity_type`` - ``sim`` / ``decision`` /
      ``outcome``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    has_activity: bool = False
    project_id: int | None = None
    project_title: str | None = None
    last_activity_at: str | None = None
    last_activity_type: str | None = None
    narrative: str = ""
    key_signals: list[dict] = []


class RunsThisMonthOut(BaseModel):
    """Response from ``GET /me/runs-this-month``.

    Tiny integer payload for the dashboard's tier-quota
    widget. Composes the count of sims created this
    calendar month against the user's tier cap.

    * ``runs_this_month`` - count of sims created since
      the first day of the current calendar month.
    * ``monthly_cap`` - the tier's monthly cap (from
      ``TIER_LIMITS``).
    * ``remaining`` - ``max(0, cap - used)``.
    * ``tier`` - tier label.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - severity-tagged display dicts.
    """

    runs_this_month: int = 0
    monthly_cap: int = 0
    remaining: int = 0
    tier: str = "FREE"
    narrative: str = ""
    key_signals: list[dict] = []


class DecisionVelocityOut(BaseModel):
    """Response from ``GET /me/decision-velocity``.

    Average gap between a completed sim and the user's
    first decision on that project. Useful for the
    dashboard's "decision speed" widget.

    * ``sample_count`` - sim/decision pairs counted.
    * ``average_gap_hours`` / ``median_gap_hours`` -
      mean / median gap in hours (None when no pairs).
    * ``fastest_gap_hours`` / ``slowest_gap_hours`` -
      min / max gap in hours.
    * ``verdict`` - ``FAST`` (<= 4h) / ``NORMAL``
      (<= 24h) / ``SLOW`` (> 24h) / ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    sample_count: int = 0
    average_gap_hours: float | None = None
    median_gap_hours: float | None = None
    fastest_gap_hours: float | None = None
    slowest_gap_hours: float | None = None
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class OutcomeVelocityOut(BaseModel):
    """Response from ``GET /me/outcome-velocity``.

    Average gap between a completed sim and the user's
    first outcome on that project. Useful for the
    dashboard's "outcome speed" widget.

    * ``sample_count`` - sim/outcome pairs counted.
    * ``average_gap_hours`` / ``median_gap_hours`` -
      mean / median gap in hours (None when no pairs).
    * ``fastest_gap_hours`` / ``slowest_gap_hours`` -
      min / max gap in hours.
    * ``verdict`` - ``FAST`` (<= 24h) / ``NORMAL``
      (<= 168h / 7d) / ``SLOW`` (> 168h) /
      ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    sample_count: int = 0
    average_gap_hours: float | None = None
    median_gap_hours: float | None = None
    fastest_gap_hours: float | None = None
    slowest_gap_hours: float | None = None
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class DecisionRateOut(BaseModel):
    """Response from ``GET /me/decision-rate``.

    Decision utilization: number of decisions per
    completed sim across the user's portfolio. Useful
    for the dashboard's "decision rate" widget.

    * ``sim_count`` - total completed sims.
    * ``decision_count`` - total decisions.
    * ``rate_per_sim`` - ``decision_count / sim_count``
      (None when sim_count is 0).
    * ``verdict`` - ``HIGH`` (>= 1.0) / ``NORMAL``
      (>= 0.5) / ``LOW`` (< 0.5) / ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    sim_count: int = 0
    decision_count: int = 0
    rate_per_sim: float | None = None
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class OutcomeRateOut(BaseModel):
    """Response from ``GET /me/outcome-rate``.

    Outcome coverage: number of outcomes per completed
    sim across the user's portfolio. Analog of
    /me/decision-rate but for outcomes.

    * ``sim_count`` - total completed sims.
    * ``outcome_count`` - total outcomes.
    * ``rate_per_sim`` - ``outcome_count / sim_count``
      (None when sim_count is 0).
    * ``verdict`` - ``HIGH`` (>= 0.5) / ``NORMAL``
      (>= 0.25) / ``LOW`` (< 0.25) /
      ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    sim_count: int = 0
    outcome_count: int = 0
    rate_per_sim: float | None = None
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class DecisionToOutcomeDelayOut(BaseModel):
    """Response from ``GET /me/decision-to-outcome-delay``.

    Average gap between a decision and the user's next
    outcome on the same project. Closes the loop on the
    decision->outcome chain (decision-velocity measures
    sim->decision, outcome-velocity measures sim->outcome,
    this one measures decision->outcome).

    * ``sample_count`` - decision/outcome pairs counted.
    * ``average_gap_hours`` / ``median_gap_hours`` -
      mean / median gap in hours (None when no pairs).
    * ``fastest_gap_hours`` / ``slowest_gap_hours`` -
      min / max gap in hours.
    * ``verdict`` - ``FAST`` (<= 24h) / ``NORMAL``
      (<= 168h / 7d) / ``SLOW`` (> 168h) /
      ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    sample_count: int = 0
    average_gap_hours: float | None = None
    median_gap_hours: float | None = None
    fastest_gap_hours: float | None = None
    slowest_gap_hours: float | None = None
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


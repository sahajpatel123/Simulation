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


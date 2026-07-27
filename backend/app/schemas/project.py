from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectPatch(BaseModel):
    """Partial update for a dossier (title rename, description edits)."""

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=5000)


class ProjectDuplicateIn(BaseModel):
    """Body for ``POST /projects/{id}/duplicate``."""

    new_title: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional override title. When omitted, the duplicate uses "
            '"<original> (copy)" / "(copy N)" naming.'
        ),
    )
    include_simulations: bool = Field(
        default=False,
        description=(
            "When true, snapshots of the source project's completed "
            "simulations are copied into the duplicate. Default false — "
            "duplicates are intentionally clean for A/B variants."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description=(
            "When true, return the planned payload without writing to "
            "the DB. Useful for previewing the duplicate in the dashboard."
        ),
    )


class ProjectDuplicateOut(BaseModel):
    """Response from ``POST /projects/{id}/duplicate``."""

    model_config = ConfigDict(  # type: ignore[assignment]
        json_schema_extra={
            "example": {
                "project": {
                    "id": 99,
                    "title": "My Idea (copy)",
                    "status": "DRAFT",
                    "user_id": 7,
                },
                "source_project_id": 42,
                "simulations_copied": 0,
                "environment_copied": True,
                "dry_run": False,
            }
        }
    )

    project: "ProjectOut"  # type: ignore[assignment]
    source_project_id: int
    simulations_copied: int = 0
    environment_copied: bool = False
    dry_run: bool = False


class ProjectCreate(BaseModel):
    title: str = Field(default="Untitled", max_length=500)
    description: str = Field(..., max_length=5000)
    intake_mode: Literal["IDEA", "MID_BUILD", "PRE_LAUNCH"] = "IDEA"
    landing_page_url: str | None = Field(default=None, max_length=2048)
    # Cap both the list length AND each string item. ``Field(max_length=50)``
    # only constrains the list — without per-item caps a user could submit
    # 50 strings of 10MB each, which would then be concatenated into the
    # LLM prompt via "Shipped features: ..." in intake_processor.
    mvp_feature_list: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=50
    )
    existing_product_description: str | None = Field(default=None, max_length=5000)
    dossier_axis: Literal["software", "hardware"] = "software"


class BriefSave(BaseModel):
    """Body for POST /projects/{id}/brief.

    Replaces the prior ``payload: dict`` so Pydantic enforces types,
    length caps, and field presence — the prior contract accepted any
    JSON shape and let the handler reach for ``payload.get("...")``
    with no length cap, so a 10MB ``positioning`` string could be
    persisted to the DB on a single request.
    """

    positioning: str = Field(default="", max_length=2000)
    features: list[str] = Field(default_factory=list, max_length=5)
    hook: str = Field(default="", max_length=1000)
    mark_complete: bool = False


class BriefAssistRequest(BaseModel):
    """Body for POST /projects/{id}/brief/assist.

    Replaces the prior ``payload: dict``. ``mode`` and ``field`` are
    pinned to a known enum so the handler can't be tricked into
    dispatching to an arbitrary LLM mode.
    """

    mode: Literal["refine", "suggest", "critique"]
    field: Literal["positioning", "features", "hook"]
    current_value: str = Field(default="", max_length=2000)


class ProjectOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    status: str
    dossier_axis: str | None = None
    precis: str | None = None
    readings_json: str | None = None
    precis_title_fingerprint: str | None = None
    is_archived: bool = False
    brief_positioning: str | None = None
    brief_features_json: str | None = None
    brief_hook: str | None = None
    brief_completed_at: datetime | None = None
    tags: list[str] = []

    model_config = {"from_attributes": True}


# ProjectDuplicateOut references ProjectOut (defined above). Resolve the
# forward reference so Pydantic can build the nested model.
ProjectDuplicateOut.model_rebuild()


class ProjectListResponse(BaseModel):
    projects: list[ProjectOut]
    total: int


class ProjectSearchListResponse(BaseModel):
    """Response from ``GET /projects/search``.

    ``has_more`` is the cursor-pagination signal: when ``True`` the
    client should fetch the next page using the smallest ``id`` in
    the current batch as the ``before_id`` argument.
    """

    projects: list[ProjectOut]
    total: int
    has_more: bool
    next_before_id: int | None = None


class ProjectTagsPatch(BaseModel):
    """Body for ``PUT /projects/{id}/tags``.

    Replaces the project's tag set with the supplied list. Empty
    body (``{"tags": []}``) is the canonical "clear all" payload — a
    separate DELETE-everything route would be redundant.
    """

    tags: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Canonical tag list. Each tag is lowercase, deduped, "
            "max 32 chars, and may contain only [a-z0-9_-]."
        ),
    )


class ProjectTagsOut(BaseModel):
    """Response from ``PUT /projects/{id}/tags`` and ``DELETE /projects/{id}/tags/{tag}``."""

    id: int
    tags: list[str]


class ProjectTagRenameIn(BaseModel):
    """Body for ``PUT /projects/tags/{old_tag}``.

    Used to rename a tag across every project the user owns. The new
    name is canonicalised through the same normalise_tags contract
    so callers can't sneak in invalid characters or break the cap.
    """

    new: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description=(
            "Canonical tag name to replace the old one with. Must "
            "satisfy the normalise_tags contract (lowercase, "
            "[a-z0-9_-], <=32 chars)."
        ),
    )


class ProjectTagRenameOut(BaseModel):
    """Response from ``PUT /projects/tags/{old_tag}``."""

    old: str
    new: str
    projects_updated: int


class ProjectTagBulkDeleteOut(BaseModel):
    """Response from ``DELETE /projects/tags/{tag}``."""

    tag: str
    projects_updated: int


class NextBestActionSource(BaseModel):
    """Pointer to the data that drove the next-best-action."""

    kind: str = ""
    ref_id: int | None = None
    ref_label: str | None = None


class NextBestActionOut(BaseModel):
    """Response from ``GET /projects/{id}/next-action``.

    Single-payload "what should I do right now?" answer
    composed from the latest simulation's top critical
    finding, the oldest pending decision, and the project's
    calibration-health verdict.

    * ``title`` — short headline (renders as the dashboard
      CTA label).
    * ``action`` — imperative verb phrase ("TIGHTEN
      PricingArchitect" / "Review & decide" / "Start a
      simulation").
    * ``reason`` — one-sentence explanation the dashboard
      renders as supporting context / tooltip.
    * ``severity`` — ``ok`` / ``watch`` / ``critical`` so
      the dashboard can colour-code the CTA.
    * ``category`` — discriminator for the dashboard icon
      (``miscalibration`` / ``pending_decision`` /
      ``calibration_health`` / ``first_sim`` / ``no_signal``).
    * ``source`` — pointer to the underlying data.
    * ``fallback`` — True when the answer is a generic
      nudge (e.g. "Run another simulation") rather than a
      data-driven recommendation.
    """

    title: str = ""
    action: str = ""
    reason: str = ""
    severity: str = "ok"
    category: str = "no_signal"
    source: NextBestActionSource = NextBestActionSource()
    fallback: bool = True


class ActivityEvent(BaseModel):
    """One entry in the per-project activity feed."""

    type: str = ""
    occurred_at: str = ""
    ref_id: int | None = None
    title: str = ""
    summary: str = ""
    severity: str = "ok"


class ActivityFeedOut(BaseModel):
    """Response from ``GET /projects/{id}/activity-feed``.

    Chronological (newest-first) timeline of the project's
    recent events — sims created / completed / failed,
    decisions created / completed / failed, outcomes
    submitted. Capped at 50 events so the dashboard
    timeline tile stays scannable.

    * ``event_count`` — total events found before capping.
    * ``events`` — capped list of :class:`ActivityEvent`.
    * ``narrative`` — one paragraph summary.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard's "what's
      important" strip.
    """

    event_count: int = 0
    events: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class ConvergenceCheckOut(BaseModel):
    """Response from ``GET /projects/{id}/convergence``.

    When a founder runs the same brief multiple times, do
    the predicted conversion rates converge (good — stable)
    or scatter (bad — unreliable)? Without this, the
    predicted numbers aren't trustworthy.

    * ``sim_count`` — sim rows considered (capped at 25).
    * ``mean_pcr`` / ``std_dev`` / ``cv`` — population
      statistics on ``predicted_conversion_rate``.
    * ``verdict`` — ``CONVERGED`` (CV < 5%),
      ``MILDLY_VARIANT`` (5% <= CV < 15%),
      ``DIVERGED`` (CV >= 15%), or
      ``INSUFFICIENT_DATA`` (fewer than 3 usable sims).
    * ``min_pcr`` / ``max_pcr`` / ``range_pcr`` — spread
      bounds for the dashboard tile.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    sim_count: int = 0
    mean_pcr: float = 0.0
    std_dev: float = 0.0
    cv: float = 0.0
    verdict: str = "INSUFFICIENT_DATA"
    min_pcr: float = 0.0
    max_pcr: float = 0.0
    range_pcr: float = 0.0
    narrative: str = ""
    key_signals: list[dict] = []


    intervention_count: int = 0
    difficulty_breakdown: dict[str, int] = {}
    priority_breakdown: dict[str, int] = {}
    category_breakdown: dict[str, int] = {}
    quick_win_count: int = 0
    top_interventions: list[dict] = []
    generated_at: str | None = None
    stale: bool = True
    narrative: str = ""
    key_signals: list[dict] = []


class ProjectHealthOut(BaseModel):
    """Response from ``GET /projects/{id}/health``.

    Per-project qualitative health verdict — 0-100 score +
    3-bucket verdict (HEALTHY ≥70 / NEEDS_ATTENTION
    40-69 / AT_RISK ≤40). Composed from the project's
    latest sim confidence, critical-finding count,
    pending-decision count, outcome presence, and
    assumption weak-link count.

    Different from /me/account-health (user-level, across
    all projects) — this is per-project. The dashboard's
    project-list view can use it to sort projects by
    health.

    * ``project_health_score`` — integer in
      ``[0, MAX_SCORE]``.
    * ``verdict`` — ``HEALTHY`` / ``NEEDS_ATTENTION`` /
      ``AT_RISK``.
    * ``score_breakdown`` — per-dimension contribution
      map (positive points + negative penalties).
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    project_health_score: int = 0
    verdict: str = "AT_RISK"
    score_breakdown: dict[str, int] = {}
    narrative: str = ""
    key_signals: list[dict] = []


class PremortemDigestOut(BaseModel):
    """Response from ``GET /projects/{id}/premortem-digest``.

    Per-project digest of the AI-generated premortem
    analysis (``project.premortem_json``) so the dashboard
    can render a "what could go wrong?" tile without
    fanning out to the generator.

    * ``premortem_count`` — total non-empty failure modes.
    * ``severity_breakdown`` — ``{CRITICAL/HIGH/...: count}``
      so the tile can render a small stacked bar.
    * ``top_failure_modes`` — capped (5) list sorted by
      ``impact`` DESC — the most fatal first.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    premortem_count: int = 0
    severity_breakdown: dict[str, int] = {}
    top_failure_modes: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class RecommendationsDigestOut(BaseModel):
    """Response from ``GET /projects/{id}/recommendations-digest``.

    Per-project composition of premortem + intervention
    recommendations so the dashboard's "what does TheCee
    recommend?" tile renders one payload without fanning
    out to /premortem-digest and /intervention-digest.

    * ``recommendation_count`` — total top recommendations
      (capped at 8 by MAX_TOP).
    * ``critical_failure_count`` — CRITICAL items in the
      premortem top list.
    * ``quick_win_count`` — LOW-difficulty + priority
      score > 0.70 items in the intervention top list.
    * ``top_recommendations`` — capped list sorted by
      ``max(impact_score, priority_score)`` DESC.
    * ``narrative`` — one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` — ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    recommendation_count: int = 0
    critical_failure_count: int = 0
    quick_win_count: int = 0
    top_recommendations: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class AdoptionMilestonesOut(BaseModel):
    """Response from ``GET /projects/{id}/adoption-milestones``.

    Onboarding progress tracker ("have you done the
    basics?"). Computes a 0-100 progress percentage +
    per-milestone boolean map so the dashboard can render
    a milestone progress bar without checking each
    component separately.

    Standard milestones:
    1. brief_completed
    2. assumptions_extracted (>= 3 non-hidden)
    3. first_sim_run
    4. first_decision_enqueued
    5. first_outcome_recorded
    6. premortem_run
    7. interventions_run
    """

    milestone_count: int = 0
    completed_count: int = 0
    progress_pct: int = 0
    milestones: dict[str, bool] = {}
    milestone_order: list[str] = []
    narrative: str = ""
    key_signals: list[dict] = []


class ProjectExportOut(BaseModel):
    """Response from ``GET /projects/{id}/export``.

    Single-payload export of one project's full state -
    brief, assumptions, simulations, decisions, outcomes,
    premortem, interventions. Useful for offline archive,
    co-founder handoff, or LLM context window.
    """

    exported_at: str = ""
    schema_version: int = 1
    project_meta: dict = {}
    brief: dict = {}
    assumptions: list[dict] = []
    simulations: list[dict] = []
    decisions: list[dict] = []
    outcomes: list[dict] = []
    premortem: dict = {}
    interventions: dict = {}


class StaleCheckOut(BaseModel):
    """Response from ``GET /projects/{id}/stale-check``.

    Data-freshness lens: surfaces which sources feeding
    the project's predictions are out of date so the
    founder can refresh them. Inverse of activity-feed
    (which shows what just happened) - stale-check shows
    what is NOT recent.

    * ``stale_count`` - number of stale sources.
    * ``sources_checked`` - total sources checked (6).
    * ``sources`` - per-source list with severity +
      recommendation.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity,
      display}`` dicts for the dashboard tiles.
    """

    stale_count: int = 0
    sources_checked: int = 0
    sources: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class StatusBannerOut(BaseModel):
    """Response from ``GET /projects/{id}/status-banner``.

    Single one-liner status for the project header.
    Cheap to fetch, useful for surfacing the project's
    state at a glance.

    * ``status`` - one of ``Healthy``, ``Action needed``,
      ``Stale``, or ``Empty``.
    * ``severity`` - ``ok`` / ``watch`` / ``critical``.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    status: str = "Empty"
    severity: str = "watch"
    narrative: str = ""
    key_signals: list[dict] = []


class ConfidenceExplainerOut(BaseModel):
    """Response from ``GET /projects/{id}/confidence-explainer``.

    Decomposes the latest completed sim's confidence
    score into its contributing factors so the dashboard
    can show *why* the confidence is what it is.

    * ``confidence_score`` - the same 0..1 from the sim
      (``sim.confidence_score``).
    * ``factors`` - list of
      ``{label, value, factor}`` dicts (one per
      contributing factor). ``factor`` is the 0..1
      subscore for that factor.
    * ``narrative`` - one paragraph string the dashboard
      renders as plain text.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    confidence_score: float = 0.0
    factors: list[dict] = []
    narrative: str = ""
    key_signals: list[dict] = []


class LatestSnapshotOut(BaseModel):
    """Response from ``GET /projects/{id}/latest-snapshot``.

    Focused "what is the current state of this project?"
    payload. Different from project-export (historical
    full bundle) and projects-summary (per-user grid).
    This is per-project, fast, latest-only.
    """

    project_id: int | None = None
    project_title: str | None = None
    project_status: str = "UNKNOWN"
    brief_completed: bool = False
    latest_simulation: dict | None = None
    latest_decision: dict | None = None
    latest_outcome: dict | None = None
    latest_assumption_extraction: dict | None = None
    snapshot_at: str = ""
    narrative: str = ""
    key_signals: list[dict] = []


class SimFailureRateOut(BaseModel):
    """Response from ``GET /me/sim-failure-rate``.

    Single "what % of your sims failed?" payload so
    the dashboard can show a system-reliability widget.

    * ``total_simulations`` - total sims across the
      user's projects.
    * ``failed_simulations`` - sims with status
      ``FAILED``.
    * ``failure_rate_pct`` - 0..100 percent.
    * ``verdict`` - ``RELIABLE`` (<= 5%) /
      ``ACCEPTABLE`` (<= 15%) / ``UNRELIABLE`` (> 15%) /
      ``INSUFFICIENT_DATA``.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    total_simulations: int = 0
    failed_simulations: int = 0
    failure_rate_pct: float = 0.0
    verdict: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class RunsPerWeekOut(BaseModel):
    """Response from ``GET /me/runs-per-week``.

    "Activity over time" payload: the number of sims
    the user ran in each of the last 4 weeks, suitable
    for a small bar chart.

    * ``weeks`` - list of ``{week_start, sim_count}``.
    * ``total_simulations`` - sum across all weeks.
    * ``average_per_week`` - ``total / len(weeks)`` (0 if
      no data).
    * ``trend`` - ``UP`` (latest > earliest) / ``DOWN``
      (latest < earliest) / ``STEADY`` (equal) /
      ``INSUFFICIENT_DATA`` (< 2 weeks).
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity, display}``.
    """

    weeks: list[dict] = []
    total_simulations: int = 0
    average_per_week: float = 0.0
    trend: str = "INSUFFICIENT_DATA"
    narrative: str = ""
    key_signals: list[dict] = []


class MostActiveWeekdayOut(BaseModel):
    """Response from ``GET /me/most-active-weekday``.

    Single "what day of the week are you most active?"
    payload so the dashboard can show a personal
    schedule insight.

    * ``total_actions`` - total sim + decision + outcome
      actions counted.
    * ``most_active_weekday`` - 0 (Monday) - 6 (Sunday),
      or ``None`` when no data.
    * ``most_active_count`` - count on the busiest
      weekday.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    total_actions: int = 0
    most_active_weekday: int | None = None
    most_active_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []


class OldestOpenItemOut(BaseModel):
    """Response from ``GET /me/oldest-open-item``.

    Single "what's been sitting longest?" payload so
    the dashboard can surface the age of the user's
    oldest unaddressed activity (sim / decision /
    outcome).

    * ``oldest_age_days`` - age in days (None when no
      data).
    * ``oldest_type`` - ``sim`` / ``decision`` /
      ``outcome``.
    * ``oldest_project_id`` - id of the project that
      owns the oldest item.
    * ``oldest_created_at`` - ISO timestamp.
    * ``narrative`` - one paragraph string.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    oldest_age_days: int | None = None
    oldest_type: str | None = None
    oldest_project_id: int | None = None
    oldest_created_at: str | None = None
    narrative: str = ""
    key_signals: list[dict] = []


class RecentOutcomesOut(BaseModel):
    """Response from ``GET /me/recent-outcomes``.

    "What happened recently?" payload: the last 5
    outcomes across the user's projects, suitable for a
    dashboard widget.

    * ``outcomes`` - capped (5) list of
      ``{outcome_id, project_id,
      actual_conversion_rate, created_at}``.
    * ``outcome_count`` - number of outcomes in the
      list (0..5).
    * ``narrative`` - one paragraph string with best
      vs worst conversion rates when data is present.
    * ``key_signals`` - ``{label, value, severity,
      display}``.
    """

    outcomes: list[dict] = []
    outcome_count: int = 0
    narrative: str = ""
    key_signals: list[dict] = []

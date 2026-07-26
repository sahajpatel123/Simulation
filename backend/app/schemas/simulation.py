from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SimulationCreate(BaseModel):
    project_id: int
    consumer_volume: int = Field(default=10000, ge=100, le=100000)


class SimulationOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results_json: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationStatusOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    task_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SimulationBatchStatusOut(BaseModel):
    """Response from ``GET /simulations/batch``.

    ``items`` is the ordered list of simulations the caller owns
    that matched the requested ids. ``not_found`` lists the ids
    that were either non-existent or owned by a different user —
    we never 404 the whole batch just because one id is bad.

    ``status_counts`` is a ``{status: count}`` summary of the
    returned items, so dashboard widgets can render "5 running, 12
    completed" without re-iterating the list. ``filtered_by_since``
    is the timestamp actually applied (echoed back so the UI can
    pin it for the next incremental poll).
    """

    items: list[SimulationStatusOut]
    not_found: list[int]
    requested: int
    status_counts: dict[str, int] = {}
    filtered_by_since: datetime | None = None


class FindingsAggregateOut(BaseModel):
    """Response from ``GET /simulations/aggregate/findings``.

    Portfolio view of domain findings across N simulations:

    * ``total_findings`` — every finding across every sim in the batch.
    * ``filtered_findings`` — count of findings at or above the
      ``min_severity`` filter.
    * ``severity_breakdown`` — ``{CRITICAL/WARNING/INFO: count}``
      across *all* findings, ignoring the filter.
    * ``by_architect`` — per-architect rollup, sorted by
      ``finding_count DESC, critical_count DESC, name ASC``.
    * ``by_cluster`` — per-cluster rollup (which user segments are
      most affected), sorted by ``finding_count DESC, critical DESC,
      cluster_id ASC``.
    * ``top_architects`` — first ``top_n`` architect names (sorted).
    * ``top_findings`` — first ``top_n`` findings by conversion_impact
      DESC (tiebreaker: severity DESC, then architect + cluster).
    * ``architect_filter`` — echoed back (whitespace-stripped, but
      *not* casefolded — the UI can show the caller's original input).
    """

    total_findings: int = 0
    filtered_findings: int = 0
    severity_breakdown: dict[str, int] = {}
    by_architect: list[dict] = []
    by_cluster: list[dict] = []
    top_architects: list[str] = []
    top_findings: list[dict] = []
    simulation_count: int = 0
    simulations_with_findings: int = 0
    shared_domain_count: int = 0
    architect_filter: str | None = None


class ArchitectAccuracyBridgeOut(BaseModel):
    """Response from ``GET /simulations/aggregate/architect-accuracy``.

    Cross-references per-simulation findings with per-simulation
    outcomes so the dashboard can answer "for the sims where the
    Pricing architect flagged a CRITICAL finding, did the model
    actually over- or under-predict conversion?" — i.e. the
    architect's alerts are calibrated against the truth.

    * ``simulation_count`` — total sims in the input (incl. ones
      without outcomes).
    * ``outcome_attached_sim_count`` — sims with at least one
      finding AND a non-null predicted+actual outcome (the
      denominator of the calibration averages).
    * ``by_architect`` — per-architect rollup sorted by
      ``|calibration_variance| DESC, finding_count DESC, name ASC``
      so the most-biased architect surfaces first. Each row
      carries:

      * ``calibrated_sim_count`` — sims with findings AND an
        outcome.
      * ``finding_only_sim_count`` — sims with findings but NO
        outcome (ground truth not yet attached).
      * ``ground_truth_coverage`` —
        ``calibrated_sim_count / (calibrated + finding_only)``;
        zero when the architect had no findings on any sim.
      * ``calibration_variance`` — mean (predicted − actual)
        across the calibrated sims.
      * ``calibration_direction`` — ``OVER_PREDICTS`` /
        ``UNDER_PREDICTS`` / ``BALANCED`` / ``INSUFFICIENT_DATA``.
      * ``recommendation`` — derived action label:
        ``TIGHTEN`` (over-prediction), ``LOOSEN`` (under-prediction),
        ``TRUSTED`` (balanced), ``INSUFFICIENT_DATA``.
      * ``needs_review`` — boolean: ``True`` when the direction
        is ``OVER_PREDICTS`` or ``UNDER_PREDICTS``.

    * ``most_biased_architects`` — first ``top_n`` architect names
      by ``|calibration_variance|`` DESC.
    * ``tighten_count`` / ``loosen_count`` / ``trusted_count`` /
      ``insufficient_data_count`` — top-level counts so the
      dashboard has four summary tiles (one per action).
    * ``min_severity`` — echoed back (whitespace-stripped and
      uppercased).
    """

    by_architect: list[dict] = []
    most_biased_architects: list[str] = []
    simulation_count: int = 0
    outcome_attached_sim_count: int = 0
    tighten_count: int = 0
    loosen_count: int = 0
    trusted_count: int = 0
    insufficient_data_count: int = 0
    min_severity: str = "INFO"


class ClustersAggregateOut(BaseModel):
    """Response from ``GET /simulations/aggregate/clusters``.

    Portfolio view of cluster-level predicted conversion across
    N simulations — the "which user segment underperforms most
    consistently?" view. Each simulation contributes a
    ``cluster_breakdown`` (``cluster_id → conversion_rate``) and
    the aggregate groups by cluster across the batch.

    * ``by_cluster`` — per-cluster rollup sorted by
      ``mean_conversion ASC, observation_count DESC, cluster_id ASC``
      so the worst-performing cluster surfaces first. Each row
      carries ``stability``, ``observation_ratio``,
      ``under_observed``, and ``needs_attention`` flags so the
      dashboard can filter "show me only the data-quality
      warnings" without recomputing.
    * ``top_laggards`` — first ``top_n`` cluster ids by worst mean
      conversion (ASC).
    * ``top_performers`` — first ``top_n`` cluster ids by best mean
      conversion (DESC).
    * ``simulation_count`` — total sims in the input.
    * ``clusters_seen`` — how many unique cluster ids appeared
      across the batch.
    * ``under_observed_count`` — number of clusters with
      ``observation_count / simulation_count`` below 30%.
    * ``needs_attention_count`` — number of clusters where
      ``under_observed`` is True or ``stability`` is
      ``HIGH_VARIANCE``. The dashboard's single "X segments
      need a closer look" tile.
    """

    by_cluster: list[dict] = []
    top_laggards: list[str] = []
    top_performers: list[str] = []
    simulation_count: int = 0
    clusters_seen: int = 0
    under_observed_count: int = 0
    needs_attention_count: int = 0


class OutcomesDigestOut(BaseModel):
    """Response from ``GET /simulations/aggregate/outcomes``.

    Portfolio view of predicted-vs-actual conversion accuracy across
    N simulations that have founder-recorded outcomes attached — the
    "calibration at scale" view. Each Outcome row contributes one
    ``(predicted, actual)`` pair (we keep the latest outcome per
    simulation id).

    * ``mae`` — Mean Absolute Error of the conversion rate (|predicted
      − actual|). Higher = less calibrated.
    * ``mape`` — Mean Absolute Percentage Error. Pairs where
      actual == 0 are excluded so the aggregate doesn't blow up.
    * ``rmse`` — Root Mean Squared Error (penalises outliers).
    * ``mae_count`` / ``mape_count`` — pair counts fed into each
      metric (often differ — MAPE drops zero-actuals).
    * ``outlier_count`` — pairs with |variance| above the (clamped)
      ``outlier_threshold`` query param. Default 0.10 (10pp).
    * ``direction_breakdown`` — ``{over, under, exact}`` histogram so
      the UI can render "we over-predicted 6 / under-predicted 2".
    * ``per_pair`` — raw (predicted, actual, variance, is_outlier,
      sim_id) tuples for scatter plots. ``sim_id`` is ``None`` when
      the caller did not supply positional sim ids.
    * ``simulation_count`` — total pairs in the input (incl. ones
      with no predicted value).
    * ``with_predictions`` — how many pairs had a non-null predicted
      value (the numerator of MAE / MAPE / RMSE).
    * ``worst_offender_sim_id`` — the sim id with the largest
      ``|variance|`` across actionable rows; ``None`` when no
      actionable rows exist or no sim ids were supplied. The UI
      can drill into "which simulation is making us look bad?".
    * ``confidence_label`` — one of ``WELL_CALIBRATED``,
      ``NEEDS_ATTENTION``, ``POORLY_CALIBRATED``, ``INSUFFICIENT_DATA``,
      bucketed from MAE so the dashboard can render a one-word
      summary tile.
    """

    mae: float = 0.0
    mape: float = 0.0
    rmse: float = 0.0
    mae_count: int = 0
    mape_count: int = 0
    outlier_count: int = 0
    direction_breakdown: dict[str, int] = {
        "over": 0,
        "under": 0,
        "exact": 0,
    }
    per_pair: list[dict] = []
    simulation_count: int = 0
    with_predictions: int = 0
    worst_offender_sim_id: int | None = None
    confidence_label: str = "INSUFFICIENT_DATA"


class PortfolioSummaryOut(BaseModel):
    """Response from ``GET /simulations/portfolio-summary``.

    One-call fusion of the four cross-simulation aggregates
    (findings, outcomes, clusters, architect-accuracy) into a
    single dashboard payload. Designed for the portfolio-view
    home screen so the founder sees "12 sims · 0.07 MAE · 2
    architects flagged TIGHTEN · NEEDS_ATTENTION" without
    issuing four separate requests.

    * ``simulation_count`` — echoed from the request.
    * ``findings_summary`` — reduced view of
      :class:`FindingsAggregateOut`: total / filtered /
      severity_breakdown / shared_domain_count /
      top_critical_architects / simulations_with_findings.
    * ``outcomes_summary`` — reduced view of
      :class:`OutcomesDigestOut`: mae / mape / rmse / mae_count /
      outlier_count / direction_breakdown / confidence_label /
      worst_offender_sim_id.
    * ``clusters_summary`` — reduced view of
      :class:`ClustersAggregateOut`: clusters_seen /
      under_observed_count / needs_attention_count /
      top_laggards.
    * ``architect_accuracy_summary`` — reduced view of
      :class:`ArchitectAccuracyBridgeOut`:
      outcome_attached_sim_count / tighten_count / loosen_count /
      trusted_count / insufficient_data_count /
      most_biased_architects.
    * ``correlated_bias_count`` — number of architect names that
      appear in BOTH ``findings_summary.top_critical_architects``
      AND ``architect_accuracy_summary.most_biased_architects``.
      Higher = more real bias signal.
    * ``data_quality_score`` — fraction of sims with both findings
      AND an outcome. Closer to 1.0 = better ground truth
      coverage.
    * ``overall_health`` — one of ``HEALTHY`` /
      ``NEEDS_ATTENTION`` / ``CRITICAL`` / ``INSUFFICIENT_DATA``.
    * ``key_recommendations`` — list of one-line actionable hints
      distilled from each sub-aggregate (e.g. "Tighten
      calibration for 2 over-predicting architect(s)"). Capped
      so the dashboard tile stays readable; ordered by priority.
    * ``next_action`` — single primary CTA string derived from
      ``overall_health`` (e.g. "Review correlated bias and
      recalibrate top architects" when CRITICAL). The
      dashboard's headline button text.
    """

    simulation_count: int = 0
    findings_summary: dict = {}
    outcomes_summary: dict = {}
    clusters_summary: dict = {}
    architect_accuracy_summary: dict = {}
    correlated_bias_count: int = 0
    data_quality_score: float = 0.0
    overall_health: str = "INSUFFICIENT_DATA"
    key_recommendations: list[str] = []
    next_action: str = (
        "Record more outcomes to unlock calibration analysis"
    )


class PortfolioTrendOut(BaseModel):
    """Response from ``GET /simulations/portfolio-trend``.

    Diff of two portfolio summaries — earlier vs later time
    windows — so the dashboard can render "MAE dropped from
    0.12 → 0.05 over the last 30 days · NEEDS_ATTENTION →
    HEALTHY". Each window is computed independently by the
    portfolio-summary helper; the trend fuses the two.

    * ``earlier_simulation_count`` / ``later_simulation_count`` /
      ``simulation_count_delta`` — how the batch grew (or
      shrunk) across the two windows.
    * ``earlier_health`` / ``later_health`` — the overall_health
      labels from each window, echoed back.
    * ``health_transition`` — one of ``IMPROVED`` / ``DEGRADED``
      / ``STABLE`` / ``NEW`` / ``RESOLVED`` / ``MIXED``. ``NEW``
      means the earlier window had INSUFFICIENT_DATA and the
      later window has actionable data (calibration unlocked).
      ``RESOLVED`` is the inverse.
    * ``deltas`` — list of per-metric rows. Each carries
      ``metric``, ``earlier``, ``later``, ``delta``, ``direction``,
      and ``significant`` (boolean — True when |delta| exceeds
      the per-metric absolute threshold).
    * ``improving_count`` / ``degrading_count`` / ``stable_count``
      — summary counts so the dashboard can render "X up /
      Y down / Z stable" without iterating.
    * ``significant_change_count`` — how many metrics shifted
      meaningfully (passing the per-metric absolute threshold).
      A single tile for the dashboard's "N signals moved" badge.
    * ``key_shifts`` — top ``KEY_SHIFTS_LIMIT`` (3) IMPROVING /
      DEGRADING deltas by relative-change magnitude. Each row
      carries ``metric``, ``direction``, ``delta``,
      ``earlier``, ``later``, ``relative_change``. The
      dashboard's headline widget renders this list.
    * ``summary`` — one-line headline string.
    """

    earlier_simulation_count: int = 0
    later_simulation_count: int = 0
    simulation_count_delta: int = 0
    earlier_health: str = "INSUFFICIENT_DATA"
    later_health: str = "INSUFFICIENT_DATA"
    health_transition: str = "STABLE"
    deltas: list[dict] = []
    improving_count: int = 0
    degrading_count: int = 0
    stable_count: int = 0
    significant_change_count: int = 0
    key_shifts: list[dict] = []
    summary: str = ""


class ClusterDrillDownOut(BaseModel):
    """Response from ``GET /simulations/cluster-drill-down``.

    Per-cluster drill-down that complements the cross-sim
    cluster aggregate: when a cluster surfaces as a laggard in
    the portfolio view, the founder wants to drill into that
    specific cluster and see its full profile + per-sim
    conversion history + aggregate stats + stability flags.

    * ``cluster_profile`` — dict carrying the cluster's
      metadata: cluster_id, name, description, traits,
      population_weight, dominant_behavior_pattern,
      known_failure_modes, product_affinities,
      demographic_profile.
    * ``per_sim_history`` — list of per-sim rows
      (``sim_id``, ``conversion_rate``, ``is_outlier``) sorted
      by sim_id ascending (None last). Includes rows where the
      cluster was missing from the sim so the dashboard can
      render "X of Y saw this cluster".
    * ``aggregate`` — mean / min / max / std conversion,
      observation_count, is_outlier_count.
    * ``stability`` — HIGH_VARIANCE / MODERATE_VARIANCE /
      LOW_VARIANCE bucketed from coefficient of variation.
    * ``observation_ratio`` / ``under_observed`` /
      ``needs_attention`` — coverage flags mirroring the
      cross-sim aggregate.
    * ``sim_count`` — how many sims in the batch (denominator
      for observation_ratio).
    * ``recommendation`` — one-line action label derived from
      stability / under-observed / outlier_count / low-mean
      thresholds. Priority order: under-observed →
      high-variance → outliers → low-conversion → continue.
    * ``peer_comparison`` — dict comparing this cluster's
      mean to the batch's overall cluster mean: ``cluster_mean``,
      ``batch_overall_mean``, ``delta``, and ``direction``
      (``ABOVE_BATCH_MEAN`` / ``BELOW_BATCH_MEAN`` /
      ``AT_BATCH_MEAN`` / ``UNKNOWN`` when batch mean absent).
    """

    cluster_profile: dict = {}
    per_sim_history: list[dict] = []
    aggregate: dict = {}
    stability: str = "INSUFFICIENT_DATA"
    observation_ratio: float = 0.0
    under_observed: bool = False
    needs_attention: bool = False
    sim_count: int = 0
    recommendation: str = "Continue current calibration"
    peer_comparison: dict = {}


class ArchitectDrillDownOut(BaseModel):
    """Response from ``GET /simulations/architect-drill-down``.

    Per-architect drill-down that complements the cross-sim
    architect-accuracy bridge: when an architect surfaces as
    biased (OVER_PREDICTS / UNDER_PREDICTS), the founder wants
    to drill in and see the architect's full profile + per-sim
    finding history + aggregate stats + stability / coverage /
    bias flags + peer comparison vs the batch's overall
    architect accuracy.

    * ``architect_profile`` — dict carrying the architect's
      metadata: architect_name, product_types,
      domain_description, applies_to_all_products.
    * ``per_sim_history`` — list of per-sim rows
      (``sim_id``, ``finding_count``, severity counts,
      ``total_conversion_impact``, ``highest_severity``,
      ``is_outlier``). Sorted by sim_id ASC (None last).
      Includes rows where the architect had no findings so the
      dashboard can render "X of Y saw this architect".
    * ``aggregate`` — total finding / severity counts,
      total_conversion_impact, sim_with_findings_count,
      is_outlier_count.
    * ``calibration_variance`` /
      ``calibration_direction`` — echoed from the
      architect-accuracy bridge.
    * ``stability`` — HIGH_VARIANCE / MODERATE_VARIANCE /
      LOW_VARIANCE bucketed from per-sim
      total_conversion_impact CV.
    * ``observation_ratio`` / ``under_observed`` /
      ``needs_attention`` — coverage + bias flags.
    * ``sim_count`` — how many sims in the batch.
    * ``recommendation`` — one-line action label derived from
      under-observed / bias / variance / outlier priority.
    * ``peer_comparison`` — architect |calibration_variance|
      vs batch mean |calibration_variance|.
    * ``critical_clusters`` — top
      :data:`MAX_CRITICAL_CLUSTERS` cluster_ids by CRITICAL
      finding count from this architect. Each row carries
      ``cluster_id``, ``cluster_name``, ``critical_count``.
      Empty when the architect never flagged CRITICAL.
    * ``severity_timeline`` — per-sim severity snapshot list
      sorted by sim_id ASC (None last). Each row carries
      per-sim critical/warning/info/total counts + cumulative
      totals so the dashboard can render an area chart
      without re-aggregating.
    """

    architect_profile: dict = {}
    per_sim_history: list[dict] = []
    aggregate: dict = {}
    calibration_variance: float | None = None
    calibration_direction: str = "INSUFFICIENT_DATA"
    stability: str = "INSUFFICIENT_DATA"
    observation_ratio: float = 0.0
    under_observed: bool = False
    needs_attention: bool = False
    sim_count: int = 0
    recommendation: str = "Continue — architect is calibrated"
    peer_comparison: dict = {}
    critical_clusters: list[dict] = []
    severity_timeline: list[dict] = []


class ClusterDiffOut(BaseModel):
    """Response from ``GET /simulations/cluster-diff``.

    Side-by-side comparison of two clusters across N sims.
    Surfaces per-trait deltas + aggregate deltas + a similarity
    score so the founder can answer "are these two clusters
    really different?" without eyeballing the cluster catalog.

    * ``cluster_a_profile`` / ``cluster_b_profile`` — echoed
      cluster metadata (id + name).
    * ``traits_diff`` — list of per-trait rows (trait,
      cluster_a, cluster_b, delta, winner). 8 rows in the
      canonical REQUIRED_TRAITS order.
    * ``aggregate_diff`` — list of per-metric rows (metric,
      cluster_a, cluster_b, delta, winner).
    * ``similarity_score`` — float in [0.0, 1.0]; 1.0 =
      identical traits, 0.0 = maximally different.
    * ``similarity_label`` — VERY_SIMILAR / SIMILAR /
      DIFFERENT / VERY_DIFFERENT bucketed from the score.
    * ``summary`` — one-line headline string.
    * ``top_differences`` — top 3 axes (traits + aggregates)
      by ``|delta|`` DESC. Each row carries ``axis``,
      ``source`` ('trait' / 'aggregate'), ``cluster_a``,
      ``cluster_b``, ``delta``, ``winner``. The dashboard's
      'what makes them different' headline tile.
    * ``product_overlap`` — sorted, deduplicated list of
      shared product affinities (case-insensitive match).
      Empty when neither cluster has product affinities or
      there's no overlap. Useful for 'these clusters are
      often targeted together' hints.
    """

    cluster_a_profile: dict = {}
    cluster_b_profile: dict = {}
    traits_diff: list[dict] = []
    aggregate_diff: list[dict] = []
    similarity_score: float = 0.0
    similarity_label: str = "VERY_DIFFERENT"
    summary: str = ""
    top_differences: list[dict] = []
    product_overlap: list[str] = []


class ClusterOverlapMatrixOut(BaseModel):
    """Response from ``GET /simulations/cluster-overlap-matrix``.

    N×N pairwise similarity matrix across a list of N
    clusters. Powers the dashboard's 'which clusters are
    similar enough to be consolidated?' heatmap.

    * ``cluster_ids`` — ordered list of cluster ids (same
      order as the matrix rows / columns).
    * ``cluster_names`` — ordered list of human-readable
      names (defaults to id when missing).
    * ``matrix`` — N×N list of lists; symmetric with 1.0 on
      the diagonal. Cells are the pairwise similarity score
      in [0.0, 1.0].
    * ``pair_summaries`` — flat list of dicts for every
      non-self pair, sorted by score DESC. Each row carries
      ``cluster_a``, ``cluster_b``, ``score``, ``label``
      (WEAK / MODERATE / STRONG).
    * ``strong_pair_count`` — how many pairs scored ≥
      STRONG_THRESHOLD (consolidation candidates).
    * ``consolidation_candidates`` — same shape as
      ``pair_summaries`` but filtered to STRONG-only and
      sorted by score DESC. The dashboard's "merge these"
      headline list.
    * ``cluster_metadata`` — ``{cluster_id: {cluster_name,
      traits}}`` map for the heatmap's hover tooltip. The
      ``traits`` dict is in canonical REQUIRED_TRAITS order
      so the dashboard renders a stable tooltip panel.
    """

    cluster_ids: list[str] = []
    cluster_names: list[str] = []
    matrix: list[list[float]] = []
    pair_summaries: list[dict] = []
    consolidation_candidates: list[dict] = []
    cluster_metadata: dict = {}
    strong_pair_count: int = 0


class ClusterTrendOut(BaseModel):
    """Response from ``GET /simulations/cluster-trend``.

    Per-cluster conversion-rate trend over time, binned by
    month / week / day. Powers the dashboard's "is this
    cluster getting better or worse?" line chart.

    * ``cluster_id`` — echoed.
    * ``bin_size`` — echoed (month / week / day).
    * ``bins`` — list of per-bin dicts sorted chronologically.
      Each row: ``bin`` (key), ``bin_start`` (ISO 8601 UTC),
      ``mean_conversion``, ``observation_count``,
      ``sim_count``.
    * ``overall_direction`` — UP / DOWN / STABLE / UNKNOWN
      bucketed from the first vs last bin mean. STABLE when
      |delta| is within 1pp so tiny jitter doesn't read as
      'the model is drifting'.
    * ``first_bin_mean`` / ``last_bin_mean`` — for the
      dashboard's headline ("X% → Y%").
    * ``mean_delta`` — last_bin_mean − first_bin_mean, or
      None when fewer than 2 bins have data.
    * ``volatility_label`` — LOW_VOLATILITY / MODERATE /
      HIGH_VOLATILITY bucketed from the coefficient of
      variation of per-bin mean conversions. Single bin
      → HIGH_VOLATILITY (no signal to measure).
    * ``peak_bin`` — the bin with the highest mean_conversion
      (tiebreaker: observation_count DESC, then bin_start
      ASC). ``None`` when no bins have data. Carries bin /
      bin_start / mean_conversion / observation_count.
    """

    cluster_id: str = ""
    bin_size: str = "month"
    bins: list[dict] = []
    overall_direction: str = "UNKNOWN"
    first_bin_mean: float | None = None
    last_bin_mean: float | None = None
    mean_delta: float | None = None
    volatility_label: str = "HIGH_VOLATILITY"
    peak_bin: dict | None = None


class ArchitectLeaderboardOut(BaseModel):
    """Response from ``GET /simulations/architect-leaderboard``.

    Single ranked list of architects across the batch so the
    dashboard can surface 'top architects to investigate'
    without iterating all 21 architects.

    * ``leaderboard`` — ranked list sorted by ``score`` DESC.
      Each row: ``architect_name``, ``finding_count``,
      ``calibration_variance``, ``calibration_direction``,
      ``recommendation``, ``score``, ``priority_label``.
    * ``priority_counts`` — ``{HIGH, MEDIUM, LOW, NONE}``
      histogram for the dashboard's summary tile.
    * ``total_architects`` — how many architects were
      considered (including uncalibrated ones with score 0).
    * ``top_n`` — the cap actually applied.
    * ``top_recommendation`` — the most common recommendation
      label across the top-N entries (tiebreaker: alphabetical
      for deterministic output). Falls back to the default
      'Continue — architect is calibrated' when the
      leaderboard is empty.
    * ``score_distribution`` — count of leaderboard rows in
      each score band (``score_zero`` / ``score_low`` /
      ``score_moderate`` / ``score_high``). Useful for the
      dashboard's histogram tile.
    """

    leaderboard: list[dict] = []
    priority_counts: dict = {}
    top_recommendation: str = (
        "Continue — architect is calibrated"
    )
    score_distribution: dict = {}
    total_architects: int = 0
    top_n: int = 0


class ArchitectBiasTrendOut(BaseModel):
    """Response from ``GET /simulations/architect-bias-trend``.

    Per-architect |calibration_variance| trend over time so
    the founder can see whether a biased architect is
    getting better, stable, or getting worse.

    * ``architect_name`` / ``bin_size`` — echoed.
    * ``bins`` — per-bin dict sorted chronologically. Each
      row: ``bin``, ``bin_start`` (ISO 8601 UTC),
      ``mean_abs_variance``, ``mean_signed_variance``,
      ``observation_count``.
    * ``overall_direction`` — IMPROVING / DEGRADING /
      STABLE bucketed from first vs last bin's |variance|.
      IMPROVING means the bias shrank (good); DEGRADING
      means it grew (bad).
    * ``first_bin_abs_variance`` /
      ``last_bin_abs_variance`` — for the dashboard's
      headline ("X% → Y%").
    * ``mean_abs_delta`` — last − first, or None when fewer
      than 2 bins have data.
    * ``current_bias_label`` — WELL_CALIBRATED / BIASED /
      UNKNOWN bucketed from the LAST bin's |variance|.
    * ``bias_direction_distribution`` — histogram of bins
      classified by signed mean_variance (OVER_PREDICTS /
      UNDER_PREDICTS / BALANCED). The dashboard renders
      "this architect has over-predicted in 3 of 5 bins"
      without iterating.
    * ``peak_bias_bin`` — the bin with the highest
      mean_abs_variance (tiebreaker: latest bin_start).
      Carries bin / bin_start / mean_abs_variance /
      mean_signed_variance / direction. ``None`` when no
      bins have data.
    """

    architect_name: str = ""
    bin_size: str = "month"
    bins: list[dict] = []
    overall_direction: str = "UNKNOWN"
    first_bin_abs_variance: float | None = None
    last_bin_abs_variance: float | None = None
    mean_abs_delta: float | None = None
    current_bias_label: str = "UNKNOWN"
    bias_direction_distribution: dict = {}
    peak_bias_bin: dict | None = None


class FindingsTrendOut(BaseModel):
    """Response from ``GET /simulations/findings-trend``.

    Per-bin findings-severity counts so the dashboard can
    render "CRITICAL findings peaked at 12 on day X ·
    trending DOWN −40 % week-over-week" alongside the bias
    trend.

    * ``bin_size`` / ``min_severity`` — echoed.
    * ``bins`` — per-bin dict sorted chronologically. Each
      row: ``bin``, ``bin_start`` (ISO 8601 UTC),
      ``critical_count``, ``warning_count``, ``info_count``,
      ``finding_count`` (total at-or-above min_severity),
      ``sim_count``.
    * ``overall_direction`` — IMPROVING (fewer CRITICALs over
      time) / DEGRADING / STABLE / UNKNOWN bucketed from
      first vs last bin's CRITICAL count.
    * ``first_bin_critical`` /
      ``last_bin_critical`` — for the dashboard's headline.
    * ``mean_delta_critical`` — last − first, or None when
      fewer than 2 bins have data.
    * ``peak_critical_bin`` — the bin with the highest
      CRITICAL count (tiebreaker: latest bin_start). None
      when no CRITICAL findings have been recorded.
    * ``critical_finding_distribution`` — histogram of bins
      bucketed by critical_count (zero / low 1-2 /
      moderate 3-5 / high 6+). Lets the dashboard render
      "N bins with 0 · M bins with 1-2 · ..." without
      iterating.
    * ``total_finding_count`` / ``total_critical_count`` /
      ``total_warning_count`` / ``total_info_count`` —
      per-severity totals across all bins.
    """

    bin_size: str = "day"
    min_severity: str = "INFO"
    bins: list[dict] = []
    overall_direction: str = "UNKNOWN"
    first_bin_critical: int = 0
    last_bin_critical: int = 0
    mean_delta_critical: int | None = None
    peak_critical_bin: dict | None = None
    critical_finding_distribution: dict = {}
    total_finding_count: int = 0
    total_critical_count: int = 0
    total_warning_count: int = 0
    total_info_count: int = 0


class ProjectPortfolioRollupOut(BaseModel):
    """Response from ``GET /simulations/project-portfolio-rollup``.

    Per-project rollup so the dashboard's 'all my projects'
    view can show which project has the most sims, the most
    recent activity, and the worst calibration.

    * ``projects`` — list of per-project rollup rows sorted by
      ``simulation_count`` DESC then ``project_id`` ASC. Each
      row: ``project_id``, ``project_title``,
      ``simulation_count``, ``latest_sim_id``,
      ``latest_sim_created_at`` (ISO 8601 UTC), mean
      predicted / actual conversion across the project's
      sims, ``miscalibrated_sim_count`` (sims where
      |predicted − actual| exceeds the confidence threshold).
    * ``total_projects`` — unique project count.
    * ``total_simulations`` — sum of ``simulation_count``.
    * ``confidence_threshold`` — echoed.
    """

    projects: list[dict] = []
    total_projects: int = 0
    total_simulations: int = 0
    confidence_threshold: float = 0.02


class SimulationResultOut(BaseModel):
    id: int
    project_id: int
    status: str
    consumer_volume: int
    results: dict | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    cluster_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    domain_findings: list[Any] = Field(default_factory=list)
    primary_failure_domain: str = "unknown"
    highest_value_cluster: dict[str, Any] = Field(default_factory=dict)
    architect_accountability: dict[str, Any] = Field(default_factory=dict)
    product_type_detected: str = ""
    cluster_narrative: str = ""
    signal_quality: float | None = None
    user_blindspots: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"from_attributes": True}

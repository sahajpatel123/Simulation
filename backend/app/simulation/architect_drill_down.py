"""
Pure helpers for the per-architect drill-down endpoint.

Mirrors :mod:`cluster_drill_down` but for a single architect
across N simulations. When the cross-sim architect-accuracy
bridge surfaces a biased architect (e.g. PricingArchitect with
a calibration_direction of OVER_PREDICTS), the founder wants
to drill in and see:

* The architect's full profile (name, product_types, optional
  domain description).
* Per-sim finding history — every sim that has at least one
  finding from this architect, with the highest-severity
  finding on that sim, the count of findings, and the
  conversion impact total.
* Aggregate stats — finding_count, critical_count, warning_count,
  info_count, total_conversion_impact.
* Stability + coverage flags mirroring the cross-sim aggregate.
* Recommendation — one-line action label derived from the
  same priority order as the cluster drill-down (under-observed
  → high-variance → outliers → low-conversion → continue),
  adapted for architects: we surface bias via the
  ``calibration_variance`` and ``calibration_direction`` fields
  the bridge computed.
* Peer comparison — this architect's calibration_variance vs
  the batch's overall mean |calibration_variance|.

The helper takes primitive args (architect profile fields +
per-sim finding rows) so it stays pure. The route layer
resolves the architect class from the registry and walks the
batch's ``results_json.domain_findings``.
"""
from __future__ import annotations

# Outlier threshold — count of findings per sim that, when
# exceeded, flags the sim as an "outlier sim" for this
# architect. Default 5 findings/sim is "above typical" without
# being so low it flags almost every batch.
DEFAULT_OUTLIER_FINDING_THRESHOLD: int = 5

# Under-observed threshold — fraction of batch sims that must
# carry at least one finding from this architect to be
# considered "well-observed". Mirrors clusters_aggregate so the
# dashboard's wording stays consistent.
UNDER_OBSERVED_RATIO: float = 0.30

# Stability label thresholds — coefficient of variation on
# per-sim total_conversion_impact. Same convention as the
# cluster drill-down.
LOW_VARIANCE_MAX_CV: float = 0.15
MODERATE_VARIANCE_MAX_CV: float = 0.50

LABEL_HIGH_VARIANCE: str = "HIGH_VARIANCE"
LABEL_MODERATE_VARIANCE: str = "MODERATE_VARIANCE"
LABEL_LOW_VARIANCE: str = "LOW_VARIANCE"

# Below this |calibration_variance| the architect is "trusted";
# above it we surface an investigation hint. Mirrors the
# outcomes-digest bias threshold.
LOW_CALIBRATION_THRESHOLD: float = 0.02

# Peer-comparison band — within this many absolute units of
# |calibration_variance| the architect is "AT_BATCH_LEVEL".
PEER_PEAK_BAND: float = 0.01

# Peer-comparison direction labels.
PEER_ABOVE: str = "ABOVE_BATCH_LEVEL"
PEER_BELOW: str = "BELOW_BATCH_LEVEL"
PEER_AT_PEAK: str = "AT_BATCH_LEVEL"
PEER_UNKNOWN: str = "UNKNOWN"

# Recommendation labels — the dashboard renders one of these
# as the primary CTA. Stable so the UI can hard-code the set.
RECO_COLLECT_MORE_OUTCOMES: str = (
    "Collect more outcomes — under-observed"
)
RECO_INVESTIGATE_BIAS: str = (
    "Investigate bias — calibration variance above threshold"
)
RECO_INVESTIGATE_OUTLIERS: str = "Investigate outlier sim(s)"
RECO_RECALIBRATE_VARIANCE: str = (
    "Recalibrate — high variance across sims"
)
RECO_TRUSTED: str = "Continue — architect is calibrated"

# Cap on the critical_clusters list — keeps the dashboard tile
# readable and prevents one noisy architect from spamming 20
# cluster rows.
MAX_CRITICAL_CLUSTERS: int = 5
MIN_CRITICAL_COUNT: int = 1


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float or return ``None``."""
    import math
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value):
        return None
    return value


def _severity_rank(severity: str) -> int:
    """Severity ordering — higher rank = more severe."""
    return {
        "INFO": 1,
        "WARNING": 2,
        "CRITICAL": 3,
    }.get(severity.upper(), 0)


def _stability_label(std: float, mean: float) -> str:
    """Bucket coefficient of variation on per-sim
    conversion-impact totals into a stability label.
    """
    if mean <= 0.0:
        return LABEL_HIGH_VARIANCE
    cv = std / mean
    if cv < LOW_VARIANCE_MAX_CV:
        return LABEL_LOW_VARIANCE
    if cv < MODERATE_VARIANCE_MAX_CV:
        return LABEL_MODERATE_VARIANCE
    return LABEL_HIGH_VARIANCE


def _build_recommendation(
    *,
    under_observed: bool,
    stability: str,
    is_outlier_count: int,
    abs_calibration_variance: float | None,
) -> str:
    """Pick the highest-priority recommendation label.

    Priority order (most actionable first):
      1. Under-observed — can't trust the data.
      2. Bias detected — |calibration_variance| above threshold.
      3. HIGH_VARIANCE — model output noisy across sims.
      4. Outliers present — at least one sim exceeded the
         threshold.
      5. Default — TRUSTED (architect is calibrated).
    """
    if under_observed:
        return RECO_COLLECT_MORE_OUTCOMES
    if (
        abs_calibration_variance is not None
        and abs_calibration_variance > LOW_CALIBRATION_THRESHOLD
    ):
        return RECO_INVESTIGATE_BIAS
    if stability == LABEL_HIGH_VARIANCE:
        return RECO_RECALIBRATE_VARIANCE
    if is_outlier_count >= 1:
        return RECO_INVESTIGATE_OUTLIERS
    return RECO_TRUSTED


def _build_peer_comparison(
    abs_calibration_variance: float | None,
    batch_overall_abs_variance: float | None,
) -> dict:
    """Compare |calibration_variance| to the batch's overall
    mean |calibration_variance|.

    Returns a dict the dashboard can render directly:
      * ``architect_abs_variance`` — echoed.
      * ``batch_overall_abs_variance`` — echoed (None when the
        route couldn't compute it).
      * ``delta`` — architect − batch (signed), or None.
      * ``direction`` — ABOVE_BATCH_LEVEL / BELOW_BATCH_LEVEL /
        AT_BATCH_LEVEL / UNKNOWN.
    """
    out = {
        "architect_abs_variance": (
            round(abs_calibration_variance, 6)
            if abs_calibration_variance is not None
            else None
        ),
        "batch_overall_abs_variance": (
            round(batch_overall_abs_variance, 6)
            if batch_overall_abs_variance is not None
            else None
        ),
        "delta": None,
        "direction": PEER_UNKNOWN,
    }
    if (
        abs_calibration_variance is None
        or batch_overall_abs_variance is None
    ):
        return out
    delta = abs_calibration_variance - batch_overall_abs_variance
    out["delta"] = round(delta, 6)
    if abs(delta) < PEER_PEAK_BAND:
        out["direction"] = PEER_AT_PEAK
    elif delta > 0:
        out["direction"] = PEER_ABOVE
    else:
        out["direction"] = PEER_BELOW
    return out


def _build_critical_clusters(
    architect_name: str,
    per_sim_findings: list[
        tuple[int | None, list[dict]]
    ],
) -> list[dict]:
    """Top clusters by CRITICAL findings from this architect.

    Filters every per-sim finding to (architect match +
    CRITICAL severity + valid cluster_id), aggregates counts
    per cluster, sorts by count DESC then cluster_id ASC,
    caps at :data:`MAX_CRITICAL_CLUSTERS`. Returns an empty
    list when the architect never flagged a CRITICAL finding.
    """
    counts: dict[str, dict] = {}
    for _sim_id, findings in per_sim_findings:
        for f in findings:
            if not isinstance(f, dict):
                continue
            if (
                str(f.get("architect_name", "")).lower()
                != architect_name.lower()
            ):
                continue
            if str(f.get("severity", "INFO")).upper() != "CRITICAL":
                continue
            cluster_id = str(f.get("cluster_id", "")).strip()
            if not cluster_id:
                continue
            slot = counts.setdefault(
                cluster_id,
                {
                    "cluster_id": cluster_id,
                    "cluster_name": str(
                        f.get("cluster_name", cluster_id)
                    ),
                    "critical_count": 0,
                },
            )
            slot["critical_count"] += 1
    rows = sorted(
        counts.values(),
        key=lambda r: (-r["critical_count"], r["cluster_id"]),
    )
    return rows[:MAX_CRITICAL_CLUSTERS]


def _build_severity_timeline(
    per_sim_findings: list[
        tuple[int | None, list[dict]]
    ],
) -> list[dict]:
    """Per-sim severity snapshot for the dashboard's timeline.

    Each row carries ``sim_id``, ``critical_count``,
    ``warning_count``, ``info_count``, ``finding_count``,
    plus cumulative totals so the dashboard can render an
    "area chart" without re-aggregating on the client.

    Sorted by sim_id ASC; None sim_ids go last.
    """
    rows: list[dict] = []
    cum_crit = 0
    cum_warn = 0
    cum_info = 0
    cum_total = 0
    for sim_id, findings in per_sim_findings:
        crit = sum(
            1 for f in findings
            if isinstance(f, dict)
            and str(f.get("severity", "INFO")).upper() == "CRITICAL"
        )
        warn = sum(
            1 for f in findings
            if isinstance(f, dict)
            and str(f.get("severity", "INFO")).upper() == "WARNING"
        )
        info = sum(
            1 for f in findings
            if isinstance(f, dict)
            and str(f.get("severity", "INFO")).upper() == "INFO"
        )
        total = crit + warn + info
        cum_crit += crit
        cum_warn += warn
        cum_info += info
        cum_total += total
        rows.append({
            "sim_id": sim_id,
            "critical_count": crit,
            "warning_count": warn,
            "info_count": info,
            "finding_count": total,
            "cumulative_critical": cum_crit,
            "cumulative_warning": cum_warn,
            "cumulative_info": cum_info,
            "cumulative_total": cum_total,
        })
    rows.sort(
        key=lambda r: (
            r["sim_id"] is None,
            r["sim_id"] if r["sim_id"] is not None else 0,
        )
    )
    return rows


def build_architect_drill_down(
    architect_name: str,
    *,
    product_types: list[str] | None = None,
    domain_description: str = "",
    per_sim_findings: list[
        tuple[int | None, list[dict]]
    ] | None = None,
    calibration_variance: float | None = None,
    calibration_direction: str = "INSUFFICIENT_DATA",
    outlier_finding_threshold: int = (
        DEFAULT_OUTLIER_FINDING_THRESHOLD
    ),
    batch_overall_abs_variance: float | None = None,
) -> dict:
    """Build the per-architect drill-down payload.

    Args:
        architect_name: the canonical architect name (e.g.
            "PricingArchitect").
        product_types: list of product types this architect is
            active for (empty list = applies to all).
        domain_description: optional free-text summary of the
            architect's domain.
        per_sim_findings: list of ``(sim_id, [finding dicts])``
            tuples — one per sim in the batch. ``sim_id`` may be
            ``None``; finding dicts follow the schema persisted
            by the engine (architect_name, severity,
            conversion_impact, etc.). Only findings whose
            ``architect_name`` matches ``architect_name`` are
            considered (other architects' findings in the same
            sim are ignored).
        calibration_variance: mean (predicted − actual) across
            sims where this architect had findings AND an
            outcome, as computed by the architect-accuracy
            bridge. ``None`` when no calibration data exists.
        calibration_direction: the bridge-computed direction
            (OVER_PREDICTS / UNDER_PREDICTS / BALANCED /
            INSUFFICIENT_DATA). Echoed back.
        outlier_finding_threshold: per-sim finding-count
            threshold above which the sim counts as an outlier.
        batch_overall_abs_variance: the batch's mean
            |calibration_variance| across all architects. Used
            by ``peer_comparison``.

    Returns:
        A dict matching :class:`ArchitectDrillDownOut`:

        * ``architect_profile`` — dict of the architect's
          metadata.
        * ``per_sim_history`` — list of per-sim rows
          (sim_id, finding_count, critical_count, warning_count,
          info_count, total_conversion_impact, highest_severity,
          is_outlier).
        * ``aggregate`` — total finding_count, severity counts,
          total_conversion_impact, sim_with_findings_count,
          is_outlier_count.
        * ``calibration_variance`` / ``calibration_direction``
          — echoed.
        * ``stability`` — HIGH_VARIANCE / MODERATE_VARIANCE /
          LOW_VARIANCE on per-sim total_conversion_impact.
        * ``observation_ratio`` / ``under_observed`` /
          ``needs_attention``.
        * ``recommendation`` — one-line action label.
        * ``peer_comparison`` — architect |variance| vs batch
          overall |variance|.
        * ``sim_count`` — how many sims in the batch.
    """
    product_types = list(product_types or [])
    per_sim_findings = per_sim_findings or []

    profile = {
        "architect_name": architect_name,
        "product_types": product_types,
        "domain_description": domain_description,
        "applies_to_all_products": len(product_types) == 0,
    }

    sim_count = len(per_sim_findings)

    history_rows: list[dict] = []
    impacts: list[float] = []
    total_finding_count = 0
    total_critical = 0
    total_warning = 0
    total_info = 0
    total_impact = 0.0
    sim_with_findings = 0
    outlier_sim_count = 0
    threshold = max(1, int(outlier_finding_threshold))

    for sim_id, findings in per_sim_findings:
        # Filter to findings from THIS architect only — the
        # batch carries findings from every architect, but the
        # drill-down is for one.
        own = [
            f for f in findings
            if isinstance(f, dict)
            and str(f.get("architect_name", "")).lower()
            == architect_name.lower()
        ]
        if not own:
            history_rows.append({
                "sim_id": sim_id,
                "finding_count": 0,
                "critical_count": 0,
                "warning_count": 0,
                "info_count": 0,
                "total_conversion_impact": 0.0,
                "highest_severity": None,
                "is_outlier": False,
            })
            continue
        sim_with_findings += 1
        crit = sum(
            1 for f in own
            if str(f.get("severity", "INFO")).upper() == "CRITICAL"
        )
        warn = sum(
            1 for f in own
            if str(f.get("severity", "INFO")).upper() == "WARNING"
        )
        info = sum(
            1 for f in own
            if str(f.get("severity", "INFO")).upper() == "INFO"
        )
        own_impact = sum(
            float(_safe_impact(f.get("conversion_impact")) or 0.0)
            for f in own
        )
        highest = max(
            (str(f.get("severity", "INFO")).upper() for f in own),
            key=_severity_rank,
            default=None,
        )
        is_outlier = len(own) > threshold
        if is_outlier:
            outlier_sim_count += 1
        total_finding_count += len(own)
        total_critical += crit
        total_warning += warn
        total_info += info
        total_impact += own_impact
        impacts.append(own_impact)
        history_rows.append({
            "sim_id": sim_id,
            "finding_count": len(own),
            "critical_count": crit,
            "warning_count": warn,
            "info_count": info,
            "total_conversion_impact": round(own_impact, 6),
            "highest_severity": highest,
            "is_outlier": is_outlier,
        })

    # Sort by sim_id ASC (None last) so the dashboard renders a
    # stable order.
    history_rows.sort(
        key=lambda r: (
            r["sim_id"] is None,
            r["sim_id"] if r["sim_id"] is not None else 0,
        )
    )

    # Per-impact aggregate.
    if impacts:
        mean_impact = sum(impacts) / len(impacts)
        if len(impacts) >= 2:
            mean_sq = sum(i * i for i in impacts) / len(impacts)
            variance = max(0.0, mean_sq - mean_impact * mean_impact)
            std_impact = (
                variance * len(impacts) / (len(impacts) - 1)
            ) ** 0.5
        else:
            std_impact = 0.0
    else:
        mean_impact = 0.0
        std_impact = 0.0
    aggregate = {
        "finding_count": total_finding_count,
        "critical_count": total_critical,
        "warning_count": total_warning,
        "info_count": total_info,
        "total_conversion_impact": round(total_impact, 6),
        "sim_with_findings_count": sim_with_findings,
        "is_outlier_count": outlier_sim_count,
    }

    stability = _stability_label(std_impact, mean_impact)
    observation_ratio = (
        sim_with_findings / sim_count if sim_count > 0 else 0.0
    )
    under_observed = observation_ratio < UNDER_OBSERVED_RATIO
    needs_attention = (
        under_observed
        or stability == LABEL_HIGH_VARIANCE
        or (
            calibration_variance is not None
            and abs(calibration_variance) > LOW_CALIBRATION_THRESHOLD
        )
    )

    abs_calibration = (
        abs(calibration_variance)
        if calibration_variance is not None
        else None
    )
    recommendation = _build_recommendation(
        under_observed=under_observed,
        stability=stability,
        is_outlier_count=outlier_sim_count,
        abs_calibration_variance=abs_calibration,
    )
    peer_comparison = _build_peer_comparison(
        abs_calibration_variance=abs_calibration,
        batch_overall_abs_variance=batch_overall_abs_variance,
    )

    return {
        "architect_profile": profile,
        "per_sim_history": history_rows,
        "aggregate": aggregate,
        "calibration_variance": (
            round(calibration_variance, 6)
            if calibration_variance is not None
            else None
        ),
        "calibration_direction": calibration_direction,
        "stability": stability,
        "observation_ratio": round(observation_ratio, 6),
        "under_observed": under_observed,
        "needs_attention": needs_attention,
        "sim_count": sim_count,
        "recommendation": recommendation,
        "peer_comparison": peer_comparison,
        "critical_clusters": _build_critical_clusters(
            architect_name, per_sim_findings
        ),
        "severity_timeline": _build_severity_timeline(
            per_sim_findings
        ),
    }


def _safe_impact(raw: object) -> float:
    """Coerce a finding's conversion_impact to float, defaulting
    to 0.0 — same convention as findings_aggregate."""
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "DEFAULT_OUTLIER_FINDING_THRESHOLD",
    "UNDER_OBSERVED_RATIO",
    "LOW_VARIANCE_MAX_CV",
    "MODERATE_VARIANCE_MAX_CV",
    "LOW_CALIBRATION_THRESHOLD",
    "PEER_PEAK_BAND",
    "PEER_ABOVE",
    "PEER_BELOW",
    "PEER_AT_PEAK",
    "PEER_UNKNOWN",
    "LABEL_HIGH_VARIANCE",
    "LABEL_MODERATE_VARIANCE",
    "LABEL_LOW_VARIANCE",
    "MAX_CRITICAL_CLUSTERS",
    "RECO_COLLECT_MORE_OUTCOMES",
    "RECO_INVESTIGATE_BIAS",
    "RECO_INVESTIGATE_OUTLIERS",
    "RECO_RECALIBRATE_VARIANCE",
    "RECO_TRUSTED",
    "build_architect_drill_down",
]
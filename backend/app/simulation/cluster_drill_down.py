"""
Pure helpers for the cluster drill-down endpoint.

The drill-down complements the cross-simulation cluster
aggregate: when the dashboard's "by_cluster" rollup surfaces a
particular cluster as a laggard (e.g. tier3_first_time_app_user
consistently underperforms), the founder wants to drill into
that specific cluster and see:

* The cluster's full profile (8 traits, population_weight,
  description, dominant_behavior_pattern, known_failure_modes,
  product_affinities, demographic_profile).
* Per-sim conversion history — every sim in the batch that
  saw this cluster, with the predicted conversion rate, in
  canonical order.
* Aggregate stats across that subset of sims (mean, min, max,
  std).
* Stability / coverage flags mirroring the cross-sim aggregate.

The helper takes primitive args (cluster profile fields + a
list of ``(sim_id, conversion_rate)`` pairs) so it stays pure
(no DB, no I/O, no imports of ClusterDefinition). The route
layer pulls the cluster definition from the registry and the
per-sim conversions from each sim's ``cluster_breakdown``.
"""
from __future__ import annotations

import math

# Outlier threshold — same convention as the cluster aggregate.
DEFAULT_OUTLIER_THRESHOLD: float = 0.10
MIN_OUTLIER_THRESHOLD: float = 0.0
MAX_OUTLIER_THRESHOLD: float = 1.0

# Under-observed threshold — a cluster is "under-observed" when
# observation_count / simulation_count < this fraction. Mirrors
# clusters_aggregate so the dashboard's wording stays consistent.
UNDER_OBSERVED_RATIO: float = 0.30

# Stability label thresholds (coefficient of variation = std /
# mean). Reuses the cluster aggregate's constants verbatim.
LOW_VARIANCE_MAX_CV: float = 0.15
MODERATE_VARIANCE_MAX_CV: float = 0.50

LABEL_HIGH_VARIANCE: str = "HIGH_VARIANCE"
LABEL_MODERATE_VARIANCE: str = "MODERATE_VARIANCE"
LABEL_LOW_VARIANCE: str = "LOW_VARIANCE"


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return ``None``.

    Mirrors clusters_aggregate._safe_conversion — a missing /
    non-numeric / out-of-range value means "we don't have a
    real conversion for this sim" and must be skipped.
    """
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
    if value < MIN_OUTLIER_THRESHOLD or value > MAX_OUTLIER_THRESHOLD:
        return None
    return value


def _stability_label(std: float, mean: float) -> str:
    """Bucket coefficient of variation into a stability label.

    Zero-mean clusters → HIGH_VARIANCE (undefined CV — better
    to flag them for investigation than silently mark them
    'low variance').
    """
    if mean <= 0.0:
        return LABEL_HIGH_VARIANCE
    cv = std / mean
    if cv < LOW_VARIANCE_MAX_CV:
        return LABEL_LOW_VARIANCE
    if cv < MODERATE_VARIANCE_MAX_CV:
        return LABEL_MODERATE_VARIANCE
    return LABEL_HIGH_VARIANCE


def normalise_outlier_threshold(raw: float | None) -> float:
    """Coerce outlier threshold query param into the allowed
    range. None → default; negative / over-1 → clamped."""
    if raw is None:
        return DEFAULT_OUTLIER_THRESHOLD
    if raw < MIN_OUTLIER_THRESHOLD:
        return MIN_OUTLIER_THRESHOLD
    if raw > MAX_OUTLIER_THRESHOLD:
        return MAX_OUTLIER_THRESHOLD
    return raw


def build_cluster_drill_down(
    cluster_id: str,
    *,
    cluster_name: str = "",
    cluster_description: str = "",
    cluster_traits: dict | None = None,
    population_weight: float = 0.0,
    dominant_behavior_pattern: str = "",
    known_failure_modes: list[str] | None = None,
    product_affinities: list[str] | None = None,
    demographic_profile: dict | None = None,
    per_sim_conversions: list[
        tuple[int | None, object]
    ] | None = None,
    outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD,
) -> dict:
    """Build the per-cluster drill-down payload.

    Args:
        cluster_id: the canonical cluster id (snake-case).
        cluster_name: human-readable name (defaults to cluster_id
            if empty).
        cluster_description: short description.
        cluster_traits: optional dict of the 8 required traits
            (income_level, digital_literacy, motivation, trust,
            price_sensitivity, risk_aversion, patience_score,
            social_orientation).
        population_weight: fraction of the simulated population
            (0.0 - 1.0).
        dominant_behavior_pattern: single-sentence pattern.
        known_failure_modes: list of failure scenarios.
        product_affinities: list of product types this cluster
            converts well on.
        demographic_profile: dict of demographic tags.
        per_sim_conversions: list of ``(sim_id, conversion_rate)``
            pairs — one per sim in the batch. ``sim_id`` may be
            ``None`` when the caller can't track ids; conversion
            values may be ``None`` / non-numeric and are
            defensively coerced.
        outlier_threshold: absolute variance above which a sim
            is marked as an outlier (default 0.10).

    Returns:
        A dict matching :class:`ClusterDrillDownOut`:

        * ``cluster_profile`` — dict of the cluster's metadata.
        * ``per_sim_history`` — list of per-sim rows
          (sim_id, conversion_rate, is_outlier) sorted by
          sim_id ascending (None sorted last).
        * ``aggregate`` — mean / min / max / std / count /
          is_outlier_count / mean std.
        * ``stability`` — HIGH_VARIANCE / MODERATE_VARIANCE /
          LOW_VARIANCE.
        * ``under_observed`` / ``needs_attention`` — coverage
          and combined flag mirroring the cross-sim aggregate.
        * ``sim_count`` — how many sims contributed (the
          denominator for ``under_observed``).
    """
    threshold = normalise_outlier_threshold(outlier_threshold)
    cluster_traits = cluster_traits or {}
    known_failure_modes = known_failure_modes or []
    product_affinities = product_affinities or []
    demographic_profile = demographic_profile or {}
    per_sim_conversions = per_sim_conversions or []

    sim_count = len(per_sim_conversions)

    profile = {
        "cluster_id": cluster_id,
        "cluster_name": cluster_name or cluster_id,
        "cluster_description": cluster_description,
        "cluster_traits": dict(cluster_traits),
        "population_weight": float(population_weight),
        "dominant_behavior_pattern": dominant_behavior_pattern,
        "known_failure_modes": list(known_failure_modes),
        "product_affinities": list(product_affinities),
        "demographic_profile": dict(demographic_profile),
    }

    # Per-sim history — keep ALL rows (incl. None-rate) so the
    # dashboard can render "X of Y saw this cluster". Defensive
    # coercion on the conversion side.
    history_rows: list[dict] = []
    rates: list[float] = []
    outlier_count = 0
    for sim_id, raw_rate in per_sim_conversions:
        rate = _safe_float(raw_rate)
        if rate is None:
            history_rows.append({
                "sim_id": sim_id,
                "conversion_rate": None,
                "is_outlier": False,
            })
            continue
        is_outlier = rate > threshold
        if is_outlier:
            outlier_count += 1
        rates.append(rate)
        history_rows.append({
            "sim_id": sim_id,
            "conversion_rate": round(rate, 6),
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

    # Aggregate stats over the rates that survived coercion.
    if rates:
        mean_rate = sum(rates) / len(rates)
        min_rate = min(rates)
        max_rate = max(rates)
        if len(rates) >= 2:
            mean_sq = sum(r * r for r in rates) / len(rates)
            variance = max(0.0, mean_sq - mean_rate * mean_rate)
            std_rate = (variance * len(rates) / (len(rates) - 1)) ** 0.5
        else:
            std_rate = 0.0
    else:
        mean_rate = 0.0
        min_rate = 0.0
        max_rate = 0.0
        std_rate = 0.0
    aggregate = {
        "mean_conversion": round(mean_rate, 6),
        "min_conversion": round(min_rate, 6),
        "max_conversion": round(max_rate, 6),
        "std_conversion": round(std_rate, 6),
        "observation_count": len(rates),
        "is_outlier_count": outlier_count,
    }

    stability = _stability_label(std_rate, mean_rate)
    observation_ratio = (
        len(rates) / sim_count if sim_count > 0 else 0.0
    )
    under_observed = observation_ratio < UNDER_OBSERVED_RATIO
    needs_attention = (
        under_observed or stability == LABEL_HIGH_VARIANCE
    )

    return {
        "cluster_profile": profile,
        "per_sim_history": history_rows,
        "aggregate": aggregate,
        "stability": stability,
        "observation_ratio": round(observation_ratio, 6),
        "under_observed": under_observed,
        "needs_attention": needs_attention,
        "sim_count": sim_count,
    }


__all__ = [
    "DEFAULT_OUTLIER_THRESHOLD",
    "MIN_OUTLIER_THRESHOLD",
    "MAX_OUTLIER_THRESHOLD",
    "UNDER_OBSERVED_RATIO",
    "LOW_VARIANCE_MAX_CV",
    "MODERATE_VARIANCE_MAX_CV",
    "LABEL_HIGH_VARIANCE",
    "LABEL_MODERATE_VARIANCE",
    "LABEL_LOW_VARIANCE",
    "normalise_outlier_threshold",
    "build_cluster_drill_down",
]
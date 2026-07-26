"""
Pure helpers for the cross-simulation cluster portfolio aggregate endpoint.

The cluster portfolio is the "where in the funnel does my user base
struggle" view: across N simulations, which consumer clusters
consistently underperform, which consistently outperform?

Each simulation in the batch contributes a ``cluster_breakdown`` —
``dict[cluster_id, conversion_rate]`` — produced by the Conductor.
For every cluster that appears in any breakdown, we aggregate:

* ``mean_conversion`` — average across sims that saw this cluster.
* ``min_conversion`` / ``max_conversion`` — best / worst of the batch.
* ``observation_count`` — how many sims had this cluster in the
  breakdown (lower means the cluster was rare or excluded).
* ``std_conversion`` — sample std-dev across sims (only computed
  when ``observation_count >= 2``; otherwise ``0.0``).

The aggregate is built in Python (not SQL) because the dataset per
request is bounded by the batch cap (100 sims) and per-cluster
stats are O(N). One pass keeps the contract surface small.

We deliberately accept a ``cluster_names`` mapping rather than
importing the ``ClusterRegistry`` so the helper stays pure
(no DB, no I/O) — the route layer resolves names from the
registry before calling.
"""
from __future__ import annotations

# Default + cap for the top-laggards / top-performers lists.
DEFAULT_TOP_N: int = 5
MAX_TOP_N: int = 100

# Conversion-rate clamps. Conversion rates are stored as fractions
# in [0.0, 1.0]. A "rate" outside this range is treated as invalid
# and skipped rather than poisoning the per-cluster averages.
MIN_CONVERSION: float = 0.0
MAX_CONVERSION: float = 1.0


def _safe_conversion(raw: object) -> float | None:
    """Coerce a conversion-rate value to a finite ``float`` in
    [0.0, 1.0] or return ``None``.

    Mirrors the defensive coercion in :mod:`outcomes_digest` — a
    stray string, ``NaN`` / ``inf``, or out-of-range value means
    "we don't have a real number for this sim" and must be skipped
    so one bad row doesn't poison the cross-cluster rollup.
    """
    import math
    if raw is None:
        return None
    if isinstance(raw, bool):
        # ``bool`` is a subclass of ``int`` — refuse so True doesn't
        # sneak into the average as 1.0.
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
    if value < MIN_CONVERSION or value > MAX_CONVERSION:
        return None
    return value


def normalise_top_n(raw: int | None) -> int:
    """Coerce ``top_n`` into [1, MAX_TOP_N], default DEFAULT_TOP_N."""
    if raw is None:
        return DEFAULT_TOP_N
    if raw < 1:
        return 1
    if raw > MAX_TOP_N:
        return MAX_TOP_N
    return raw


def _extract_breakdown(sim_results: object) -> dict[str, float]:
    """Pull the ``cluster_breakdown`` out of a simulation's
    ``results_json``.

    The persisted shape varies slightly across versions:

    * ``results_json.cluster_breakdown`` — the canonical dict.
    * Older versions may store under ``conductor.cluster_breakdown``.

    Anything we can't parse becomes an empty dict so the aggregate
    doesn't crash on a stale row.
    """
    if sim_results is None:
        return {}
    if isinstance(sim_results, list):
        # Oldest shape: list of findings — no cluster_breakdown.
        return {}
    if not isinstance(sim_results, dict):
        return {}
    for key in ("cluster_breakdown", "clusters"):
        value = sim_results.get(key)
        if isinstance(value, dict):
            return value
    nested = sim_results.get("conductor")
    if isinstance(nested, dict):
        value = nested.get("cluster_breakdown")
        if isinstance(value, dict):
            return value
    return {}


def _normalise_cluster_names(
    raw: object,
) -> dict[str, str]:
    """Build a sanitised cluster_id → display_name mapping.

    Keys must be strings; values are coerced to strings (with
    None → key). Anything outside that contract is dropped so the
    caller can't smuggle in a 100MB blob via the ``cluster_name``
    field.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            continue
        if value is None:
            out[key] = key
        elif isinstance(value, str):
            out[key] = value
        else:
            try:
                out[key] = str(value)
            except Exception:
                continue
    return out


def aggregate_clusters(
    simulation_results: list[dict],
    *,
    cluster_names: dict[str, str] | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Aggregate cluster conversion rates across N simulations.

    Args:
        simulation_results: list of ``results_json`` payloads (one
            per simulation). Each is a dict — defensive for our
            persisted shape variants.
        cluster_names: optional mapping of ``cluster_id → display_name``
            so the output rows carry the human-readable name. When
            omitted, the cluster_id is echoed as the name.
        top_n: how many cluster ids to return in ``top_laggards``
            and ``top_performers``.

    Returns:
        A dict matching the ``ClustersAggregateOut`` schema:

        * ``by_cluster`` — per-cluster rollup, sorted by
          ``mean_conversion ASC, observation_count DESC,
          cluster_id ASC`` so the worst-performing cluster surfaces
          first. Each row carries:

          * ``cluster_id``
          * ``cluster_name`` (or the id if no name was supplied)
          * ``mean_conversion``
          * ``min_conversion``
          * ``max_conversion``
          * ``std_conversion`` (sample std-dev; 0 when count < 2)
          * ``observation_count`` (sims that saw this cluster)
          * ``total_conversion`` (sum across sims — useful for the
            portfolio "weighted" view)

        * ``top_laggards`` — first ``top_n`` cluster_ids by worst
          mean conversion (ASC). Sorted by mean_conversion ASC.
        * ``top_performers`` — first ``top_n`` cluster_ids by best
          mean conversion (DESC). Sorted by mean_conversion DESC.
        * ``simulation_count`` — how many simulations contributed.
        * ``clusters_seen`` — how many unique cluster_ids appeared
          in any breakdown.
    """
    name_lookup = _normalise_cluster_names(cluster_names)
    total = len(simulation_results)
    if total == 0:
        return {
            "by_cluster": [],
            "top_laggards": [],
            "top_performers": [],
            "simulation_count": 0,
            "clusters_seen": 0,
        }

    # Per-cluster accumulators.
    per_cluster: dict[str, list[float]] = {}

    for sim_results in simulation_results:
        breakdown = _extract_breakdown(sim_results)
        if not breakdown:
            continue
        for cluster_id, raw_value in breakdown.items():
            if not isinstance(cluster_id, str) or not cluster_id:
                continue
            value = _safe_conversion(raw_value)
            if value is None:
                continue
            per_cluster.setdefault(cluster_id, []).append(value)

    if not per_cluster:
        return {
            "by_cluster": [],
            "top_laggards": [],
            "top_performers": [],
            "simulation_count": total,
            "clusters_seen": 0,
        }

    rows: list[dict] = []
    for cluster_id, values in per_cluster.items():
        count = len(values)
        total_conv = sum(values)
        mean_conv = total_conv / count
        min_conv = min(values)
        max_conv = max(values)
        if count >= 2:
            # Sample std-dev: 1/(n-1) rather than 1/n. With a single
            # sample the variance is undefined so we pin to 0.0.
            mean_sq = sum(v * v for v in values) / count
            variance = max(0.0, mean_sq - mean_conv * mean_conv)
            std_conv = (variance * count / (count - 1)) ** 0.5
        else:
            std_conv = 0.0
        rows.append({
            "cluster_id": cluster_id,
            "cluster_name": name_lookup.get(cluster_id, cluster_id),
            "mean_conversion": round(mean_conv, 6),
            "min_conversion": round(min_conv, 6),
            "max_conversion": round(max_conv, 6),
            "std_conversion": round(std_conv, 6),
            "observation_count": count,
            "total_conversion": round(total_conv, 6),
        })

    # Sort ASC by mean_conversion — the worst clusters first, so the
    # dashboard's "by_cluster" view reads naturally.
    by_cluster_asc = sorted(
        rows,
        key=lambda r: (
            r["mean_conversion"],
            -r["observation_count"],
            r["cluster_id"],
        ),
    )
    top_laggards = [
        r["cluster_id"] for r in by_cluster_asc[: max(0, top_n)]
    ]
    # Top performers: same data, sorted DESC by mean_conversion.
    by_cluster_desc = sorted(
        rows,
        key=lambda r: (
            -r["mean_conversion"],
            -r["observation_count"],
            r["cluster_id"],
        ),
    )
    top_performers = [
        r["cluster_id"] for r in by_cluster_desc[: max(0, top_n)]
    ]

    return {
        "by_cluster": by_cluster_asc,
        "top_laggards": top_laggards,
        "top_performers": top_performers,
        "simulation_count": total,
        "clusters_seen": len(per_cluster),
    }


__all__ = [
    "DEFAULT_TOP_N",
    "MAX_TOP_N",
    "MIN_CONVERSION",
    "MAX_CONVERSION",
    "normalise_top_n",
    "aggregate_clusters",
]
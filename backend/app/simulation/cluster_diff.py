"""
Pure helpers for the cluster diff endpoint.

When the dashboard surfaces two clusters that look similar
(e.g. metro_pro vs senior_enterprise_decision_maker), the
founder wants to see exactly how they differ:

* Per-trait delta for each of the 8 required traits
  (income_level, digital_literacy, motivation, trust,
  price_sensitivity, risk_aversion, patience_score,
  social_orientation). Each delta carries a "winner" label
  (CLUSTER_A / CLUSTER_B / TIE) so the dashboard can highlight
  which side leads on each axis.
* Aggregate stats delta (mean conversion, observation count,
  is_outlier_count, stability).
* Similarity score in [0.0, 1.0] — 1.0 means the two clusters
  are identical on every input trait; 0.0 means they differ
  maximally. Useful for the dashboard's "are these really
  different?" headline.
* One-line summary string.

The helper is pure-Python (no SQL, no I/O) — the route layer
resolves both cluster definitions from the registry and runs
the cluster drill-down once per cluster before composing.
"""
from __future__ import annotations

# The 8 required trait keys. Mirrors ClusterDefinition.REQUIRED_TRAITS
# so the diff always covers the full trait surface even when one
# side is missing a few keys.
REQUIRED_TRAITS: tuple[str, ...] = (
    "income_level",
    "digital_literacy",
    "motivation",
    "trust",
    "price_sensitivity",
    "risk_aversion",
    "patience_score",
    "social_orientation",
)

# Similarity threshold above which the two clusters are
# labelled "very similar" — at or above 0.85, the dashboard
# can suggest the founder collapse them.
SIMILARITY_HIGH_THRESHOLD: float = 0.85
SIMILARITY_LOW_THRESHOLD: float = 0.50

LABEL_VERY_SIMILAR: str = "VERY_SIMILAR"
LABEL_SIMILAR: str = "SIMILAR"
LABEL_DIFFERENT: str = "DIFFERENT"
LABEL_VERY_DIFFERENT: str = "VERY_DIFFERENT"
VALID_SIMILARITY_LABELS: frozenset[str] = frozenset({
    LABEL_VERY_SIMILAR,
    LABEL_SIMILAR,
    LABEL_DIFFERENT,
    LABEL_VERY_DIFFERENT,
})


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [0.0, 1.0] or return None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if value != value:  # NaN check
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value


def _winner(a: float | None, b: float | None) -> str:
    """Pick the higher side. ``TIE`` on near-equal."""
    if a is None and b is None:
        return "TIE"
    if a is None:
        return "CLUSTER_B"
    if b is None:
        return "CLUSTER_A"
    delta = a - b
    if abs(delta) < 1e-6:
        return "TIE"
    return "CLUSTER_A" if delta > 0 else "CLUSTER_B"


def _traits_diff(
    a_traits: dict | None,
    b_traits: dict | None,
) -> list[dict]:
    """Per-trait delta with a winner label.

    Returns one row per required trait in ``REQUIRED_TRAITS``,
    in canonical order, so the dashboard can render a
    side-by-side comparison table.
    """
    a = a_traits or {}
    b = b_traits or {}
    rows: list[dict] = []
    for trait in REQUIRED_TRAITS:
        a_val = _safe_float(a.get(trait))
        b_val = _safe_float(b.get(trait))
        delta = (
            round(a_val - b_val, 6)
            if a_val is not None and b_val is not None
            else None
        )
        rows.append({
            "trait": trait,
            "cluster_a": a_val,
            "cluster_b": b_val,
            "delta": delta,
            "winner": _winner(a_val, b_val),
        })
    return rows


def _aggregate_diff(a: dict | None, b: dict | None) -> dict:
    """Diff the per-cluster aggregate dicts."""
    a = a or {}
    b = b or {}
    rows = []
    for key in (
        "mean_conversion",
        "min_conversion",
        "max_conversion",
        "std_conversion",
        "observation_count",
        "is_outlier_count",
    ):
        a_val = a.get(key)
        b_val = b.get(key)
        a_num = (
            float(a_val) if isinstance(a_val, (int, float)) else None
        )
        b_num = (
            float(b_val) if isinstance(b_val, (int, float)) else None
        )
        delta = (
            round(a_num - b_num, 6)
            if a_num is not None and b_num is not None
            else None
        )
        rows.append({
            "metric": key,
            "cluster_a": a_num,
            "cluster_b": b_num,
            "delta": delta,
            "winner": _winner(a_num, b_num),
        })
    return rows


def _similarity_score(traits_diff: list[dict]) -> float:
    """Mean (1 − |trait_delta|) across the 8 required traits.

    Each trait is in [0.0, 1.0] so |trait_delta| is in [0.0,
    1.0]. The score is in [0.0, 1.0] where 1.0 = identical
    traits and 0.0 = maximally different. ``None`` deltas
    (missing traits on either side) are skipped so they
    don't penalise the score.
    """
    scored = [
        abs(d["delta"]) for d in traits_diff
        if d["delta"] is not None
    ]
    if not scored:
        return 0.0
    avg_abs_delta = sum(scored) / len(scored)
    # Clamp to [0, 1] for safety.
    return max(0.0, min(1.0, 1.0 - avg_abs_delta))


def _similarity_label(score: float) -> str:
    """Bucket the similarity score into a dashboard label."""
    if score >= SIMILARITY_HIGH_THRESHOLD:
        return LABEL_VERY_SIMILAR
    if score >= SIMILARITY_LOW_THRESHOLD:
        return LABEL_SIMILAR
    if score >= SIMILARITY_LOW_THRESHOLD / 2:
        return LABEL_DIFFERENT
    return LABEL_VERY_DIFFERENT


def _summary(
    *,
    cluster_a_name: str,
    cluster_b_name: str,
    similarity_score: float,
    similarity_label: str,
    aggregate_diff: list[dict],
) -> str:
    """One-line headline string.

    Pulls the mean-conversion delta from aggregate_diff and
    pairs it with the similarity label.
    """
    mean_row = next(
        (r for r in aggregate_diff if r["metric"] == "mean_conversion"),
        None,
    )
    delta = mean_row["delta"] if mean_row else None
    delta_str = ""
    if delta is not None:
        sign = "+" if delta > 0 else ""
        delta_str = f" · mean conv {sign}{delta:.4f}"
    return (
        f"{cluster_a_name} vs {cluster_b_name}: "
        f"{similarity_label} (similarity {similarity_score:.2f})"
        f"{delta_str}"
    )


def build_cluster_diff(
    cluster_a_id: str,
    cluster_b_id: str,
    *,
    cluster_a_name: str = "",
    cluster_a_traits: dict | None = None,
    cluster_a_aggregate: dict | None = None,
    cluster_b_name: str = "",
    cluster_b_traits: dict | None = None,
    cluster_b_aggregate: dict | None = None,
) -> dict:
    """Build the cluster diff payload.

    Args:
        cluster_a_id: canonical id for cluster A.
        cluster_b_id: canonical id for cluster B.
        cluster_a_name / cluster_b_name: human-readable names
            (default to id when missing).
        cluster_a_traits / cluster_b_traits: dicts of the 8
            required trait values (one per ClusterDefinition).
        cluster_a_aggregate / cluster_b_aggregate: per-cluster
            aggregate dicts as produced by the cluster
            drill-down helper (mean_conversion, std,
            observation_count, is_outlier_count, etc.).

    Returns:
        A dict matching :class:`ClusterDiffOut`:

        * ``cluster_a_profile`` / ``cluster_b_profile`` —
          echoed cluster metadata (id + name).
        * ``traits_diff`` — list of per-trait rows
          (trait, cluster_a, cluster_b, delta, winner).
        * ``aggregate_diff`` — list of per-metric rows
          (metric, cluster_a, cluster_b, delta, winner).
        * ``similarity_score`` — float in [0.0, 1.0].
        * ``similarity_label`` — VERY_SIMILAR / SIMILAR /
          DIFFERENT / VERY_DIFFERENT bucketed from the score.
        * ``summary`` — one-line headline.
    """
    a_traits_rows = _traits_diff(cluster_a_traits, cluster_b_traits)
    b_aggregate_rows = _aggregate_diff(
        cluster_a_aggregate, cluster_b_aggregate
    )
    similarity_score = round(_similarity_score(a_traits_rows), 6)
    similarity_label = _similarity_label(similarity_score)
    summary = _summary(
        cluster_a_name=cluster_a_name or cluster_a_id,
        cluster_b_name=cluster_b_name or cluster_b_id,
        similarity_score=similarity_score,
        similarity_label=similarity_label,
        aggregate_diff=b_aggregate_rows,
    )

    return {
        "cluster_a_profile": {
            "cluster_id": cluster_a_id,
            "cluster_name": cluster_a_name or cluster_a_id,
        },
        "cluster_b_profile": {
            "cluster_id": cluster_b_id,
            "cluster_name": cluster_b_name or cluster_b_id,
        },
        "traits_diff": a_traits_rows,
        "aggregate_diff": b_aggregate_rows,
        "similarity_score": similarity_score,
        "similarity_label": similarity_label,
        "summary": summary,
    }


__all__ = [
    "REQUIRED_TRAITS",
    "SIMILARITY_HIGH_THRESHOLD",
    "SIMILARITY_LOW_THRESHOLD",
    "LABEL_VERY_SIMILAR",
    "LABEL_SIMILAR",
    "LABEL_DIFFERENT",
    "LABEL_VERY_DIFFERENT",
    "VALID_SIMILARITY_LABELS",
    "build_cluster_diff",
]
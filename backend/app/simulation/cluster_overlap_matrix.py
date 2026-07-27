"""
Pure helpers for the cluster-overlap matrix endpoint.

When the dashboard wants to render a heatmap of "which clusters
are similar enough to be consolidated?", it needs an N×N
matrix of pairwise similarity scores. For N clusters this is
N*(N-1)/2 unique pairs (the matrix is symmetric); the helper
computes each pair's similarity_score by reusing the same
mean(1 − |trait_delta|) calculation as the cluster diff
endpoint.

The matrix is symmetric with 1.0 on the diagonal (each
cluster is identical to itself). Cap of :data:`MAX_CLUSTERS`
prevents an expensive 50×50=2500-pair computation if the
dashboard accidentally passes every cluster id.
"""
from __future__ import annotations

from app.simulation.cluster_diff import REQUIRED_TRAITS

# Cap on the number of clusters in a single matrix. 25
# produces a 625-cell matrix (300 unique pairs); beyond
# this the dashboard heatmap becomes unreadable AND the
# O(N²) computation exceeds the 30/min/IP rate-limit
# budget for a single request.
MAX_CLUSTERS: int = 25

# Below this score, the pair is reported as a "weak"
# relationship — the dashboard can use the label to decide
# whether to suggest consolidation.
WEAK_THRESHOLD: float = 0.50
STRONG_THRESHOLD: float = 0.85

LABEL_WEAK: str = "WEAK"
LABEL_MODERATE: str = "MODERATE"
LABEL_STRONG: str = "STRONG"
VALID_RELATIONSHIP_LABELS: frozenset[str] = frozenset({
    LABEL_WEAK,
    LABEL_MODERATE,
    LABEL_STRONG,
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


def _pairwise_similarity(
    a_traits: dict,
    b_traits: dict,
) -> float:
    """Mean(1 − |trait_delta|) across REQUIRED_TRAITS.

    Mirrors :func:`cluster_diff._similarity_score` so the
    dashboard can compare single-pair diffs to the matrix
    without worrying about different formulas.
    """
    scored: list[float] = []
    for trait in REQUIRED_TRAITS:
        a = _safe_float(a_traits.get(trait))
        b = _safe_float(b_traits.get(trait))
        if a is None or b is None:
            continue
        scored.append(abs(a - b))
    if not scored:
        return 0.0
    avg_abs_delta = sum(scored) / len(scored)
    return max(0.0, min(1.0, 1.0 - avg_abs_delta))


def _relationship_label(score: float) -> str:
    """Bucket a similarity score into a relationship label."""
    if score >= STRONG_THRESHOLD:
        return LABEL_STRONG
    if score >= WEAK_THRESHOLD:
        return LABEL_MODERATE
    return LABEL_WEAK


def build_cluster_overlap_matrix(
    clusters: list[dict],
) -> dict:
    """Build the cluster-overlap matrix payload.

    Args:
        clusters: list of dicts, each carrying ``cluster_id``
            and ``traits`` (the 8 required trait values).
            Order in the input is preserved in the output.

    Returns:
        A dict matching :class:`ClusterOverlapMatrixOut`:

        * ``cluster_ids`` — ordered list of cluster ids in
          the same order as the matrix rows / columns.
        * ``cluster_names`` — ordered list of human-readable
          names (defaults to id when missing).
        * ``matrix`` — N×N list of lists; symmetric with
          1.0 on the diagonal. Cells are the pairwise
          similarity score in [0.0, 1.0].
        * ``pair_summaries`` — flat list of dicts for every
          non-self pair, sorted by ``score`` DESC. Each row:
          ``cluster_a``, ``cluster_b``, ``score``, ``label``.
          Top pairs surface first so the dashboard can render
          'most similar pairs' without iterating.
        * ``strong_pair_count`` — how many pairs scored
          ≥ STRONG_THRESHOLD (consolidation candidates).
    """
    if len(clusters) > MAX_CLUSTERS:
        raise ValueError(
            f"too many clusters ({len(clusters)}); "
            f"max is {MAX_CLUSTERS}"
        )
    if not clusters:
        return {
            "cluster_ids": [],
            "cluster_names": [],
            "matrix": [],
            "pair_summaries": [],
            "consolidation_candidates": [],
            "cluster_metadata": {},
            "strong_pair_count": 0,
        }

    cluster_ids: list[str] = []
    cluster_names: list[str] = []
    cluster_metadata: dict[str, dict] = {}
    for entry in clusters:
        cid = str(entry.get("cluster_id", "")).strip()
        if not cid:
            raise ValueError(
                "every cluster entry must supply a non-empty "
                "cluster_id"
            )
        cluster_ids.append(cid)
        cluster_names.append(
            str(entry.get("cluster_name") or cid)
        )
        # Per-cluster metadata for the heatmap tooltip — name
        # + the 8 required traits in canonical order so the
        # dashboard can render a "hover to see traits" panel
        # without re-querying.
        traits = entry.get("traits") or {}
        cluster_metadata[cid] = {
            "cluster_name": cluster_names[-1],
            "traits": {
                t: traits.get(t)
                for t in REQUIRED_TRAITS
            },
        }

    n = len(cluster_ids)
    # Pre-compute pairwise similarity so we only run
    # _pairwise_similarity once per pair.
    matrix: list[list[float]] = [
        [0.0 for _ in range(n)] for _ in range(n)
    ]
    pair_summaries: list[dict] = []
    consolidation_candidates: list[dict] = []
    strong_pair_count = 0
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            score = _pairwise_similarity(
                clusters[i].get("traits") or {},
                clusters[j].get("traits") or {},
            )
            score = round(score, 6)
            matrix[i][j] = score
            matrix[j][i] = score
            label = _relationship_label(score)
            row = {
                "cluster_a": cluster_ids[i],
                "cluster_b": cluster_ids[j],
                "score": score,
                "label": label,
            }
            pair_summaries.append(row)
            if label == LABEL_STRONG:
                strong_pair_count += 1
                consolidation_candidates.append(row)

    pair_summaries.sort(key=lambda p: (-p["score"], p["cluster_a"]))
    # consolidation_candidates already came in nested-loop
    # order (i < j, descending i), but keep them sorted by
    # score DESC for the dashboard's headline view.
    consolidation_candidates.sort(
        key=lambda p: (-p["score"], p["cluster_a"])
    )

    return {
        "cluster_ids": cluster_ids,
        "cluster_names": cluster_names,
        "matrix": matrix,
        "pair_summaries": pair_summaries,
        "consolidation_candidates": consolidation_candidates,
        "cluster_metadata": cluster_metadata,
        "strong_pair_count": strong_pair_count,
    }


__all__ = [
    "MAX_CLUSTERS",
    "WEAK_THRESHOLD",
    "STRONG_THRESHOLD",
    "LABEL_WEAK",
    "LABEL_MODERATE",
    "LABEL_STRONG",
    "VALID_RELATIONSHIP_LABELS",
    "build_cluster_overlap_matrix",
]

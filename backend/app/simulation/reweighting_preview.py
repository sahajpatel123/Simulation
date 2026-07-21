"""
Pure helpers for the reweighting-preview endpoint.

These helpers do the heavy lifting for ``GET /projects/{id}/reweighting-preview``:

  1. ``summarise_rule_bundle`` — pull the human-readable details of the rule
     bundle the engine would apply for the given inputs (suppressed clusters,
     amplification multipliers, geo/age tweaks).

  2. ``build_top_bottom_clusters`` — extract the top-N and bottom-N clusters
     by final weight, decorated with their friendly display name and source
     (``registry`` / ``amplified`` / ``suppressed``).

The route handler instantiates ``ClusterReweightingEngine`` to compute the
final weights, then hands the weights + selected rule + raw inputs to these
helpers to render the preview payload.
"""
from __future__ import annotations

from typing import Any


def summarise_rule_bundle(
    rule_key: str,
    rules: dict[str, Any],
    final_weights: dict[str, float],
    baseline_weights: dict[str, float],
    cluster_names: dict[str, str],
    top_n: int = 5,
    bottom_n: int = 5,
) -> dict[str, Any]:
    """
    Build the preview payload from a selected rule bundle and the engine's
    computed weights.

    ``rules`` shape::

        {
          "suppress": [cluster_id, ...],
          "amplify":  {cluster_id: multiplier, ...},
        }

    ``final_weights`` and ``baseline_weights`` are dicts of cluster_id → weight
    that already sum to ~1.0 (the engine normalises). ``cluster_names`` maps
    cluster_id → display name; falls back to the id when unknown.

    The returned dict matches the ``ReweightingPreviewOut`` shape but is
    produced as a plain dict so the route can extend it (e.g. add
    ``project_id``) before Pydantic validation.
    """
    suppress_list = list(rules.get("suppress", []) or [])
    amplify_dict: dict[str, float] = dict(rules.get("amplify", {}) or {})

    # Amplified entries: only show those that survived (still in final_weights
    # AND non-zero). Sort by final weight desc for readability.
    amplified_rows: list[dict[str, Any]] = []
    for cid, mult in amplify_dict.items():
        final_w = float(final_weights.get(cid, 0.0) or 0.0)
        if final_w <= 0.0:
            continue
        amplified_rows.append(
            {
                "cluster_id": cid,
                "cluster_name": cluster_names.get(cid, cid),
                "multiplier": float(mult),
                "final_weight": round(final_w, 6),
            }
        )
    amplified_rows.sort(key=lambda r: (-r["final_weight"], r["cluster_id"]))

    # Top-N clusters by final weight (with friendly name + source tag).
    ranked = sorted(
        final_weights.items(), key=lambda kv: (-float(kv[1]), kv[0])
    )

    def _source_for(cid: str, weight: float) -> str:
        if cid in suppress_list:
            return "suppressed"
        if cid in amplify_dict:
            return "amplified"
        return "registry"

    top_clusters = [
        {
            "cluster_id": cid,
            "cluster_name": cluster_names.get(cid, cid),
            "population_weight": round(float(weight), 6),
            "source": _source_for(cid, float(weight)),
        }
        for cid, weight in ranked[: max(0, top_n)]
    ]
    # Bottom-N: smallest non-zero weights first; if there are ties the
    # alphabetical order from ``ranked`` is preserved.
    bottom_clusters = [
        {
            "cluster_id": cid,
            "cluster_name": cluster_names.get(cid, cid),
            "population_weight": round(float(weight), 6),
            "source": _source_for(cid, float(weight)),
        }
        for cid, weight in ranked[-max(0, bottom_n):]
    ][::-1]  # show lowest-first reading order

    baseline_sum = round(sum(float(v) for v in baseline_weights.values()), 6)
    final_sum = round(sum(float(v) for v in final_weights.values()), 6)

    if rule_key == "DEFAULT":
        message = (
            "No specific reweighting rule applies — falling back to the "
            "baseline registry distribution."
        )
    else:
        message = (
            f"Applied rule bundle '{rule_key}' "
            f"({len(suppress_list)} suppressed, {len(amplified_rows)} amplified)."
        )

    return {
        "rule_bundle": rule_key,
        "suppressed": suppress_list,
        "amplified": amplified_rows,
        "top_clusters": top_clusters,
        "bottom_clusters": bottom_clusters,
        "baseline_weight_sum": baseline_sum,
        "total_weight_sum": final_sum,
        "message": message,
    }


__all__ = ["summarise_rule_bundle"]

"""Pure helpers for the per-user coverage-gap digest.

Inverse of the portfolio-narrative: instead of showing
what the user IS exploring, this surfaces the dimensions
the user has NEVER explored. Useful input for the
"broaden your assumption set" nudge.

The helper is pure-Python. The route layer pulls the
underlying rows and hands them to
:func:`build_coverage_gaps`.

What it counts
--------------
* **Categories** — ``Assumption.category`` values that
  appear at least once vs missing entirely. Standard
  category set is hard-coded so the digest can flag
  both "present" and "absent".
* **Sensitivities** — count by HIGH / MEDIUM / LOW /
  CRITICAL. Users with ONLY LOW-sensitivity
  assumptions are likely under-rating risk.
* **Tier coverage** — distinct cluster IDs found across
  completed sims. The platform ships 52 clusters; users
  who only ever touch 1-3 are missing coverage.

Output shape
------------
::

    {
      "covered_categories": list[str],
      "missing_categories": list[str],
      "sensitivity_breakdown": {"HIGH": n, ...},
      "covered_cluster_count": int,
      "missing_architect_count": int,
      "total_assumption_count": int,
      "narrative": str,
      "key_signals": list[dict],
    }
"""
from __future__ import annotations

# Standard assumption categories the platform supports.
# Anything outside this set is still counted under
# "covered_categories" but not flagged as missing.
STANDARD_CATEGORIES: frozenset[str] = frozenset({
    "Market",
    "Pricing",
    "DistributionChannel",
    "Onboarding",
    "Trust",
    "Pricing.Cost",
    "Retention",
    "Support",
    "Pricing.Cost",
    "Competitive",
})

# Severity buckets.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Threshold below which coverage is considered "thin".
THIN_CLUSTER_COVERAGE: int = 5


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return int(value)
    return default


def build_coverage_gaps(
    assumptions: list[dict] | None = None,
    cluster_ids: list[int] | None = None,
) -> dict:
    """Compose the per-user coverage-gap digest.

    Args:
        assumptions: list of assumption-row dicts;
            expected keys ``category`` and
            ``sensitivity``. ``is_hidden``-true rows
            are filtered out before counting.
        cluster_ids: distinct cluster IDs that have
            appeared in the user's completed sims.

    Returns:
        Dict matching the output shape described in the
        module docstring.
    """
    visible = [
        a for a in (assumptions or [])
        if isinstance(a, dict) and not a.get("is_hidden")
    ]

    # ---- Categories -------------------------------------------------
    covered_categories: set[str] = set()
    sensitivity_breakdown: dict[str, int] = {}
    for a in visible:
        cat = a.get("category")
        if isinstance(cat, str) and cat:
            covered_categories.add(cat)
        sens = (a.get("sensitivity") or "MEDIUM").upper()
        sensitivity_breakdown[sens] = (
            sensitivity_breakdown.get(sens, 0) + 1
        )

    missing_categories = sorted(
        STANDARD_CATEGORIES - covered_categories,
    )

    # ---- Cluster coverage -------------------------------------------
    covered_cluster_count = _safe_int(len(set(cluster_ids or [])))

    # ---- Architects used --------------------------------------------
    # Categories mapped to architects is a bit fuzzy; we
    # use the distinct category list as a proxy for
    # "architects the user has triggered".
    distinct_architects = len([
        c for c in covered_categories
        if c in STANDARD_CATEGORIES
    ])

    # ---- Total assumption count -------------------------------------
    total_assumption_count = len(visible)

    # ---- Key signals ------------------------------------------------
    key_signals: list[dict] = []
    key_signals.append({
        "label": "total_assumption_count",
        "value": total_assumption_count,
        "severity": (
            SIGNAL_WATCH if total_assumption_count == 0
            else SIGNAL_OK
        ),
        "display": (
            f"{total_assumption_count} assumption(s) on file"
        ),
    })
    if missing_categories:
        key_signals.append({
            "label": "missing_categories",
            "value": len(missing_categories),
            "severity": (
                SIGNAL_CRITICAL
                if len(missing_categories) >= 4 else SIGNAL_WATCH
            ),
            "display": (
                f"{len(missing_categories)} standard "
                f"category(ies) unexplored"
            ),
        })
    if (
        covered_cluster_count > 0
        and covered_cluster_count < THIN_CLUSTER_COVERAGE
    ):
        key_signals.append({
            "label": "thin_cluster_coverage",
            "value": covered_cluster_count,
            "severity": SIGNAL_WATCH,
            "display": (
                f"Only {covered_cluster_count} cluster(s) "
                f"touched — broaden to test more segments"
            ),
        })
    sensitivity_breakdown_high = sensitivity_breakdown.get(
        "HIGH", 0,
    ) + sensitivity_breakdown.get("CRITICAL", 0)
    if (
        total_assumption_count >= 5
        and sensitivity_breakdown_high == 0
    ):
        key_signals.append({
            "label": "no_high_sensitivity_assumptions",
            "value": True,
            "severity": SIGNAL_CRITICAL,
            "display": (
                "No HIGH/CRITICAL sensitivity assumption "
                "recorded — risks may be under-rated"
            ),
        })

    # ---- Narrative -------------------------------------------------
    sentences: list[str] = []
    sentences.append(
        f"Across {total_assumption_count} assumption(s) "
        f"on file, {len(covered_categories)} standard "
        f"categories are covered."
    )
    if missing_categories:
        sentences.append(
            f"Missing: {', '.join(missing_categories[:5])}"
            f"{'...' if len(missing_categories) > 5 else ''}."
        )
    if (
        covered_cluster_count > 0
        and covered_cluster_count < THIN_CLUSTER_COVERAGE
    ):
        sentences.append(
            f"Only {covered_cluster_count} cluster(s) touched "
            f"— testing more segments would broaden the read."
        )
    narrative = " ".join(sentences)

    return {
        "covered_categories": sorted(covered_categories),
        "missing_categories": missing_categories,
        "sensitivity_breakdown": sensitivity_breakdown,
        "covered_cluster_count": covered_cluster_count,
        "missing_architect_count": max(
            0, len(STANDARD_CATEGORIES) - distinct_architects,
        ),
        "total_assumption_count": total_assumption_count,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "STANDARD_CATEGORIES",
    "THIN_CLUSTER_COVERAGE",
    "SIGNAL_OK",
    "SIGNAL_WATCH",
    "SIGNAL_CRITICAL",
    "build_coverage_gaps",
]  # noqa: E501

"""
Pure helpers for the cross-simulation "architect accuracy bridge".

The bridge cross-references two existing rollups — the findings
aggregate (which architects flagged what severity) with the
outcomes digest (predicted vs actual conversion) — so the
dashboard can answer "for the sims where the Pricing architect
flagged a CRITICAL finding, did the model actually over- or
under-predict conversion?"

Per architect, we aggregate:

* ``finding_count`` — total findings (filtered by min_severity).
* ``critical_count`` / ``warning_count`` / ``info_count``.
* ``total_conversion_impact`` — sum of finding conversion impacts.
* ``calibrated_sim_count`` — how many sims had at least one
  finding from this architect AND a recorded outcome.
* ``calibration_variance`` — mean (predicted − actual) across
  those sims. Positive = over-predicted; negative = under-predicted.
* ``calibration_direction`` — one of ``OVER_PREDICTS``,
  ``UNDER_PREDICTS``, ``BALANCED``, ``INSUFFICIENT_DATA`` bucketed
  from |variance| against :data:`CALIBRATION_BIAS_THRESHOLD`.
* ``needs_review`` — combined flag: ``OVER_PREDICTS`` or
  ``UNDER_PREDICTS`` (the architect's CRITICAL flags correlated
  with bias). UI highlight.
* ``outcome_attached_sim_count`` — top-level count of how many
  sims in the batch had both findings AND an outcome.

The helper is pure-Python (no SQL) — the route layer joins
``simulations`` to ``outcomes`` before invoking. Per-sim numerics
are O(F + 1) where F is the findings count, so the total cost is
O(N * F) for N sims — bounded by the 100-sim batch cap.
"""
from __future__ import annotations

from collections import defaultdict

# Default + cap for the top-of-list (architects with the largest
# |calibration_variance|).
DEFAULT_TOP_N: int = 5
MAX_TOP_N: int = 100

# Allowlist of severities this endpoint accepts. Mirrors the
# findings_aggregate validation set so we don't silently expand
# the surface when the engine adds a new severity.
VALID_SEVERITIES: frozenset[str] = frozenset(
    {"CRITICAL", "WARNING", "INFO"}
)
DEFAULT_MIN_SEVERITY: str = "INFO"

# Severity ordering — higher rank = more severe.
_SEVERITY_RANK: dict[str, int] = {
    "INFO": 1,
    "WARNING": 2,
    "CRITICAL": 3,
}

# Calibration direction allowlist.
LABEL_OVER_PREDICTS: str = "OVER_PREDICTS"
LABEL_UNDER_PREDICTS: str = "UNDER_PREDICTS"
LABEL_BALANCED: str = "BALANCED"
LABEL_INSUFFICIENT_DATA: str = "INSUFFICIENT_DATA"
VALID_CALIBRATION_DIRECTIONS: frozenset[str] = frozenset({
    LABEL_OVER_PREDICTS,
    LABEL_UNDER_PREDICTS,
    LABEL_BALANCED,
    LABEL_INSUFFICIENT_DATA,
})

# Recommendation allowlist — the action the dashboard should take.
# Distinct from ``calibration_direction`` (the data) so the UI can
# surface both ("over-predicted" + "TIGHTEN").
LABEL_TIGHTEN: str = "TIGHTEN"
LABEL_LOOSEN: str = "LOOSEN"
LABEL_TRUSTED: str = "TRUSTED"
VALID_RECOMMENDATIONS: frozenset[str] = frozenset({
    LABEL_TIGHTEN,
    LABEL_LOOSEN,
    LABEL_TRUSTED,
    LABEL_INSUFFICIENT_DATA,
})

# A 2pp absolute variance is the same threshold used by the
# outcomes digest's confidence_label. Above 2pp = biased.
CALIBRATION_BIAS_THRESHOLD: float = 0.02


def severity_meets_min(severity: str, min_severity: str) -> bool:
    """Return True if ``severity`` is at or above ``min_severity``."""
    return _SEVERITY_RANK.get(severity, 0) >= _SEVERITY_RANK.get(
        min_severity, 0
    )


def normalise_severity(raw: str | None) -> str:
    """Return a valid severity or the default.

    Anything outside the allowlist raises ``ValueError`` so a
    typo (``?min_severity=crit``) doesn't silently downgrade the
    filter and hide critical findings.
    """
    if raw is None:
        return DEFAULT_MIN_SEVERITY
    candidate = (raw or "").strip().upper()
    if not candidate:
        return DEFAULT_MIN_SEVERITY
    if candidate not in VALID_SEVERITIES:
        allowed = ", ".join(sorted(VALID_SEVERITIES))
        raise ValueError(f"invalid severity {raw!r}; allowed: {allowed}")
    return candidate


def normalise_top_n(raw: int | None) -> int:
    """Coerce ``top_n`` into [1, MAX_TOP_N], default DEFAULT_TOP_N."""
    if raw is None:
        return DEFAULT_TOP_N
    if raw < 1:
        return 1
    if raw > MAX_TOP_N:
        return MAX_TOP_N
    return raw


def _extract_findings(sim_results: object) -> list[dict]:
    """Pull finding dicts out of a simulation's ``results_json``.

    Mirrors ``findings_aggregate._extract_findings`` so both
    helpers see the same shape variants: ``domain_findings``,
    ``findings``, or list-of-dict.
    """
    if sim_results is None:
        return []
    if isinstance(sim_results, list):
        return [f for f in sim_results if isinstance(f, dict)]
    if not isinstance(sim_results, dict):
        return []
    for key in ("domain_findings", "findings"):
        value = sim_results.get(key)
        if isinstance(value, list):
            return [f for f in value if isinstance(f, dict)]
    return []


def _safe_float(raw: object) -> float | None:
    """Coerce to a finite float in [-1.0, 1.0] or return ``None``.

    Mirrors the outcomes_digest coercion — anything outside the
    conversion-rate range is treated as "missing" so a stray
    string / bool / NaN doesn't poison the per-architect
    averages.
    """
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
    if value < -1.0 or value > 1.0:
        return None
    return value


def _safe_impact(raw: object) -> float:
    """Coerce a finding's conversion_impact to float, defaulting
    to 0.0. Mirrors findings_aggregate for stable top-findings
    sorting."""
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _calibration_direction(
    variance: float, sample_count: int
) -> str:
    """Bucket the mean variance into a direction label."""
    if sample_count <= 0:
        return LABEL_INSUFFICIENT_DATA
    if variance > CALIBRATION_BIAS_THRESHOLD:
        return LABEL_OVER_PREDICTS
    if variance < -CALIBRATION_BIAS_THRESHOLD:
        return LABEL_UNDER_PREDICTS
    return LABEL_BALANCED


def _recommendation(direction: str) -> str:
    """Map a calibration direction to a one-word action label.

    * ``OVER_PREDICTS`` → ``TIGHTEN`` — the model is over-promising,
      tighten predicted conversion values.
    * ``UNDER_PREDICTS`` → ``LOOSEN`` — the model is under-promising,
      loosen predicted conversion values (and surface the upside).
    * ``BALANCED`` → ``TRUSTED`` — calibration is good; no action.
    * ``INSUFFICIENT_DATA`` → ``INSUFFICIENT_DATA`` — collect more
      ground-truth outcomes before deciding.
    """
    if direction == LABEL_OVER_PREDICTS:
        return LABEL_TIGHTEN
    if direction == LABEL_UNDER_PREDICTS:
        return LABEL_LOOSEN
    if direction == LABEL_BALANCED:
        return LABEL_TRUSTED
    return LABEL_INSUFFICIENT_DATA


def bridge_architect_accuracy(
    pairs: list[
        tuple[dict | None, tuple[float | None, float | None]]
    ],
    *,
    min_severity: str = DEFAULT_MIN_SEVERITY,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Cross-reference per-sim findings with per-sim outcomes.

    Args:
        pairs: list of ``(results_json, (predicted, actual))``
            tuples — one per simulation in the batch. Either
            side may be ``None`` (missing); the row is still
            counted in ``simulation_count`` but excluded from
            the numeric aggregates.
        min_severity: only findings at or above this severity
            feed the per-architect rollup. Defaults to INFO.
        top_n: how many architects to surface in
            ``most_biased_architects``.

    Returns:
        A dict matching :class:`ArchitectAccuracyBridgeOut`:

        * ``simulation_count`` — total pairs in the input.
        * ``outcome_attached_sim_count`` — pairs with at least
          one finding AND a non-null predicted+actual outcome.
        * ``by_architect`` — per-architect rollup sorted by
          ``|calibration_variance| DESC, finding_count DESC,
          name ASC``. Each row carries the calibration
          direction label and a ``needs_review`` flag.
        * ``most_biased_architects`` — first ``top_n`` architect
          names by ``|calibration_variance|`` DESC.
        * ``min_severity`` — echoed back so the UI can show
          "filtering by: WARNING".
    """
    min_sev = normalise_severity(min_severity)
    effective_top_n = normalise_top_n(top_n)
    total = len(pairs)

    if total == 0:
        return {
            "by_architect": [],
            "most_biased_architects": [],
            "simulation_count": 0,
            "outcome_attached_sim_count": 0,
            "tighten_count": 0,
            "loosen_count": 0,
            "trusted_count": 0,
            "insufficient_data_count": 0,
            "min_severity": min_sev,
        }

    # Per-architect accumulators (filtered by min_severity).
    per_architect: dict[str, dict] = {}
    # Track which architects had at least one finding in a sim
    # with an attached outcome → drives ``calibrated_sim_count``.
    calibrated_architects: set[str] = set()
    # Per-architect list of variances on those calibrated sims.
    architect_variances: dict[str, list[float]] = defaultdict(list)
    # Per-architect count of sims where they had findings but NO
    # usable outcome — drives ``finding_only_sim_count`` and the
    # ``ground_truth_coverage`` ratio.
    finding_only_counts: dict[str, int] = defaultdict(int)
    # Top-level outcome_attached_sim_count (unique sims).
    outcome_attached_sims: set[int] = set()

    for sim_index, (sim_results, outcome) in enumerate(pairs):
        findings = _extract_findings(sim_results)
        if not findings:
            continue
        # Per-sim seen-architects for the calibrated_architects set.
        sim_architects: set[str] = set()
        for f in findings:
            severity = str(f.get("severity", "INFO")).upper()
            arch = str(f.get("architect_name", "unknown"))
            impact = _safe_impact(f.get("conversion_impact"))
            if not severity_meets_min(severity, min_sev):
                continue
            slot = per_architect.setdefault(
                arch,
                {
                    "architect_name": arch,
                    "finding_count": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "total_conversion_impact": 0.0,
                },
            )
            slot["finding_count"] += 1
            slot["total_conversion_impact"] += impact
            if severity == "CRITICAL":
                slot["critical_count"] += 1
            elif severity == "WARNING":
                slot["warning_count"] += 1
            else:
                slot["info_count"] += 1
            sim_architects.add(arch)

        # Only count this sim toward the calibrated aggregates if
        # the outcome has both sides numeric — otherwise we'd be
        # averaging in NaN / None.
        pred, act = outcome
        pred_f = _safe_float(pred)
        act_f = _safe_float(act)
        if pred_f is None or act_f is None:
            # Findings without ground truth — count toward
            # ``finding_only_sim_count`` so the dashboard can show
            # "X sims have findings but no outcome yet".
            for arch in sim_architects:
                finding_only_counts[arch] += 1
            continue
        if not sim_architects:
            continue
        outcome_attached_sims.add(sim_index)
        variance = pred_f - act_f
        for arch in sim_architects:
            calibrated_architects.add(arch)
            architect_variances[arch].append(variance)

    # Build the per-architect rows.
    rows: list[dict] = []
    for arch, slot in per_architect.items():
        variances = architect_variances.get(arch, [])
        calibrated_count = len(variances)
        finding_only_count = finding_only_counts.get(arch, 0)
        total_observed = calibrated_count + finding_only_count
        mean_variance = (
            sum(variances) / calibrated_count
            if calibrated_count
            else 0.0
        )
        direction = _calibration_direction(
            mean_variance, calibrated_count
        )
        # Ground-truth coverage is the share of the architect's
        # findings-driven sims that have an attached outcome. The
        # dashboard uses this to warn "calibration is based on a
        # small slice — collect more outcomes first".
        ground_truth_coverage = (
            calibrated_count / total_observed
            if total_observed > 0
            else 0.0
        )
        needs_review = direction in (
            LABEL_OVER_PREDICTS,
            LABEL_UNDER_PREDICTS,
        )
        rows.append({
            **slot,
            "calibrated_sim_count": calibrated_count,
            "finding_only_sim_count": finding_only_count,
            "ground_truth_coverage": round(ground_truth_coverage, 6),
            "calibration_variance": round(mean_variance, 6),
            "calibration_direction": direction,
            "recommendation": _recommendation(direction),
            "needs_review": needs_review,
        })

    # Sort by |calibration_variance| DESC so the most-biased
    # architects surface first, then by finding_count DESC as a
    # tiebreaker, then alphabetically.
    by_architect = sorted(
        rows,
        key=lambda r: (
            -abs(r["calibration_variance"]),
            -r["finding_count"],
            r["architect_name"],
        ),
    )
    most_biased = [
        r["architect_name"]
        for r in by_architect[: max(0, effective_top_n)]
    ]

    return {
        "by_architect": by_architect,
        "most_biased_architects": most_biased,
        "simulation_count": total,
        "outcome_attached_sim_count": len(outcome_attached_sims),
        "tighten_count": sum(
            1 for r in by_architect
            if r["recommendation"] == LABEL_TIGHTEN
        ),
        "loosen_count": sum(
            1 for r in by_architect
            if r["recommendation"] == LABEL_LOOSEN
        ),
        "trusted_count": sum(
            1 for r in by_architect
            if r["recommendation"] == LABEL_TRUSTED
        ),
        "insufficient_data_count": sum(
            1 for r in by_architect
            if r["recommendation"] == LABEL_INSUFFICIENT_DATA
        ),
        "min_severity": min_sev,
    }


__all__ = [
    "DEFAULT_TOP_N",
    "MAX_TOP_N",
    "DEFAULT_MIN_SEVERITY",
    "VALID_SEVERITIES",
    "VALID_CALIBRATION_DIRECTIONS",
    "VALID_RECOMMENDATIONS",
    "LABEL_OVER_PREDICTS",
    "LABEL_UNDER_PREDICTS",
    "LABEL_BALANCED",
    "LABEL_INSUFFICIENT_DATA",
    "LABEL_TIGHTEN",
    "LABEL_LOOSEN",
    "LABEL_TRUSTED",
    "CALIBRATION_BIAS_THRESHOLD",
    "severity_meets_min",
    "normalise_severity",
    "normalise_top_n",
    "bridge_architect_accuracy",
]
"""
Pure simulation quality gate for completed simulation results.

Answers a founder / developer question the existing analytics endpoints
assume away: *how trustworthy is this run's persisted payload?* The gate
runs deterministic integrity checks over ``results_json`` — never a re-run,
never an LLM call:

* **Results present** — non-empty payload was persisted.
* **Headline conversion bounded** — the headline rate is finite in [0, 1].
* **Agent counts consistent** — ``converted <= total_agents``.
* **Cluster breakdown present** — per-cluster data survived persistence.
* **Cluster coverage** — the breakdown covers the registered 52-cluster
  registry (catches sampling / ``cluster_parameters`` seeding regressions
  that silently drop segments).
* **Cluster rates bounded** — every per-cluster rate is finite in [0, 1].
* **Weighted-blend consistency** — the headline conversion matches the
  coverage-normalized, population-weighted cluster blend within tolerance
  (partial breakdowns are compared on the clusters that survived
  persistence, so missing segments cannot manufacture divergence).
* **Funnel sanity** — stage metrics are bounded and the ARRIVE→DECIDE
  counts never increase (PURCHASE is exempt because the funnel anchors
  it directly to the conductor-derived conversion by design).
* **Domain findings present** — the accountability engine produced output.
* **NaN/Inf free** — nothing downstream can silently poison analytics.

Each check carries a severity weight (CRITICAL / MAJOR / MINOR) and the
0..1 ``trust_score`` is the share of evaluated weight that passed, so a
missing ``raw_funnel`` on legacy rows skips (not fails) the funnel checks
without inflating the score. Verdict bands: ``>= 0.85`` PASS, ``>= 0.60``
REVIEW, otherwise FAIL.

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from app.schemas.simulation_quality import (
    QualityCheck,
    SimulationQualityOut,
    SimulationQualitySummary,
)
from app.simulation.clusters.registry import ClusterRegistry

# Severity weights drive the trust-score blend.
SEVERITY_CRITICAL: str = "CRITICAL"
SEVERITY_MAJOR: str = "MAJOR"
SEVERITY_MINOR: str = "MINOR"
SEVERITY_INFO: str = "INFO"

SEVERITY_WEIGHTS: dict[str, float] = {
    SEVERITY_CRITICAL: 1.0,
    SEVERITY_MAJOR: 0.6,
    SEVERITY_MINOR: 0.3,
    SEVERITY_INFO: 0.0,
}

VERDICT_PASS: str = "PASS"
VERDICT_REVIEW: str = "REVIEW"
VERDICT_FAIL: str = "FAIL"

PASS_THRESHOLD: float = 0.85
REVIEW_THRESHOLD: float = 0.60

# Cluster coverage bands: >= 98% is healthy, 90-98% partial, below 90% the
# results are materially incomplete.
COVERAGE_PASS: float = 0.98
COVERAGE_WARN: float = 0.90

# Absolute tolerance for headline vs demand-weighted blend divergence.
WEIGHTED_CONSISTENCY_TOLERANCE: float = 0.02

# Below this covered population weight (weights sum to 1.0 across the
# registry) a partial breakdown's normalized blend is too fragile to
# compare against the headline — skip rather than guess.
WEIGHTED_CONSISTENCY_MIN_COVERED_WEIGHT: float = 0.5

FUNNEL_ORDER: tuple[str, ...] = ("ARRIVE", "BROWSE", "CONSIDER", "DECIDE")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_signal_quality(raw: Any) -> float | None:
    """Coerce a persisted signal quality to a finite 0..1 float.

    Non-finite, out-of-range, boolean and unparseable values are
    treated as missing so a malformed legacy row can neither crash
    the quality gate nor inflate its trust score.
    """
    parsed = _safe_float(raw)
    if parsed is not None and not (0.0 <= parsed <= 1.0):
        return None
    return parsed


def _safe_int(value: Any, default: int | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _coerce_results(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _cluster_rate(raw: Any) -> float | None:
    """Extract a cluster conversion rate; ``None`` when unparseable."""
    if isinstance(raw, dict):
        rate = raw.get("conversion_rate")
        if rate is None:
            rate = raw.get("conversion")
    else:
        rate = raw
    return _safe_float(rate)


def _headline_conversion(results: dict[str, Any]) -> float | None:
    """Best-effort headline conversion from persisted result fields."""
    for key in ("population_weighted_conversion", "conversion_rate"):
        value = _safe_float(results.get(key))
        if value is not None:
            return value
    value = _safe_float(results.get("mean_conversion_rate"))
    if value is not None:
        return value
    raw_funnel = results.get("raw_funnel")
    if isinstance(raw_funnel, dict):
        return _safe_float(raw_funnel.get("conversion_rate"))
    return None


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(v) for v in value)
    return False


def _expected_cluster_ids() -> list[str]:
    return [cluster.cluster_id for cluster in ClusterRegistry().all_clusters()]


def _coverage_fraction(
    breakdown: dict[str, Any],
    expected_ids: list[str],
) -> float:
    if not expected_ids:
        return 1.0
    present = sum(1 for cid in expected_ids if cid in breakdown)
    return present / len(expected_ids)


# ---------------------------------------------------------------------------
# Individual checks. Each returns (passed, skipped, detail).
# ---------------------------------------------------------------------------

def _check_results_present(results: dict[str, Any]) -> tuple[bool, bool, str]:
    if results:
        return True, False, "results payload present"
    return False, False, "results payload is empty"


def _check_top_level_rates_bounded(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    conversion = _headline_conversion(results)
    if conversion is None:
        return (
            False,
            False,
            "no headline conversion found (population_weighted_conversion / "
            "mean_conversion_rate / raw_funnel.conversion_rate)",
        )
    if not (0.0 <= conversion <= 1.0):
        return (
            False,
            False,
            f"headline conversion {conversion:.6f} outside [0, 1]",
        )
    return True, False, f"headline conversion {conversion:.4f} within [0, 1]"


def _check_agent_counts_consistent(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    raw_funnel = results.get("raw_funnel")
    if isinstance(raw_funnel, dict):
        total = _safe_int(raw_funnel.get("total_agents"))
        converted = _safe_int(raw_funnel.get("converted"))
    else:
        total = _safe_int(results.get("total_agents"))
        converted = _safe_int(results.get("converted"))
    if total is None:
        return False, False, "total_agents missing from results"
    if total <= 0:
        return False, False, f"total_agents must be positive (got {total})"
    if converted is None:
        return False, False, "converted count missing from results"
    if converted < 0 or converted > total:
        return (
            False,
            False,
            f"converted {converted} outside [0, {total}]",
        )
    return True, False, f"converted {converted} of {total} agents"


def _check_cluster_breakdown_present(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    breakdown = results.get("cluster_breakdown")
    if isinstance(breakdown, dict) and breakdown:
        return True, False, f"{len(breakdown)} clusters in breakdown"
    return False, False, "cluster_breakdown missing or empty"


def _check_cluster_coverage(
    results: dict[str, Any],
    expected_ids: list[str],
) -> tuple[bool, bool, str]:
    breakdown = results.get("cluster_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return False, False, "cluster_breakdown missing or empty"
    fraction = _coverage_fraction(breakdown, expected_ids)
    present = sum(1 for cid in expected_ids if cid in breakdown)
    if fraction >= COVERAGE_PASS:
        return (
            True,
            False,
            f"{present}/{len(expected_ids)} clusters covered ({fraction:.0%})",
        )
    if fraction >= COVERAGE_WARN:
        return (
            False,
            False,
            f"partial coverage {present}/{len(expected_ids)} ({fraction:.0%}) — "
            "check sampling / cluster_parameters seeding",
        )
    return (
        False,
        False,
        f"low coverage {present}/{len(expected_ids)} ({fraction:.0%}) — "
        "results are materially incomplete",
    )


def _check_cluster_rates_bounded(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    breakdown = results.get("cluster_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return False, False, "cluster_breakdown missing or empty"
    bad: list[str] = []
    for cid, raw in breakdown.items():
        rate = _cluster_rate(raw)
        if rate is None or not (0.0 <= rate <= 1.0):
            bad.append(str(cid))
    if bad:
        sample = ", ".join(bad[:5])
        return (
            False,
            False,
            f"{len(bad)} cluster(s) with out-of-range or unparseable rates: {sample}",
        )
    return True, False, f"all {len(breakdown)} cluster rates within [0, 1]"


def _check_weighted_consistency(
    results: dict[str, Any],
    expected_ids: list[str],
) -> tuple[bool, bool, str]:
    headline = _headline_conversion(results)
    breakdown = results.get("cluster_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return False, False, "cluster_breakdown missing or empty"
    if _coverage_fraction(breakdown, expected_ids) < COVERAGE_WARN:
        return (
            True,
            True,
            "skipped — cluster coverage below 90%, blend not meaningful",
        )
    if headline is None:
        return True, True, "skipped — no headline conversion to compare"
    registry = ClusterRegistry()
    by_id = {cluster.cluster_id: cluster for cluster in registry.all_clusters()}
    # The conductor computes the headline over *all* 52 clusters, so a
    # partially persisted breakdown must be compared on the clusters that
    # survived persistence: normalize by the covered population weight
    # instead of summing a subset of weights (which would guarantee a
    # divergence proportional to the missing weight).
    weighted_sum = 0.0
    covered_weight = 0.0
    for cid, raw in breakdown.items():
        cluster = by_id.get(cid)
        if cluster is None:
            continue
        rate = _cluster_rate(raw)
        if rate is None:
            continue
        weighted_sum += cluster.population_weight * rate
        covered_weight += cluster.population_weight
    if covered_weight <= 0.0:
        return (
            True,
            True,
            "skipped — no registry clusters with parseable rates in breakdown",
        )
    if covered_weight < WEIGHTED_CONSISTENCY_MIN_COVERED_WEIGHT:
        return (
            True,
            True,
            f"skipped — covered population weight {covered_weight:.3f} below "
            f"{WEIGHTED_CONSISTENCY_MIN_COVERED_WEIGHT:.1f}, blend not meaningful",
        )
    blended = weighted_sum / covered_weight
    diff = abs(headline - blended)
    if diff <= WEIGHTED_CONSISTENCY_TOLERANCE:
        return (
            True,
            False,
            f"headline {headline:.4f} matches coverage-normalized weighted "
            f"blend {blended:.4f} "
            f"(|diff| {diff:.4f} <= {WEIGHTED_CONSISTENCY_TOLERANCE})",
        )
    return (
        False,
        False,
        f"headline {headline:.4f} diverges from weighted blend {blended:.4f} "
        f"(coverage-normalized; |diff| {diff:.4f} > "
        f"{WEIGHTED_CONSISTENCY_TOLERANCE})",
    )


def _raw_funnel(results: dict[str, Any]) -> dict[str, Any] | None:
    raw = results.get("raw_funnel")
    return raw if isinstance(raw, dict) else None


def _check_funnel_metrics_bounded(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    raw_funnel = _raw_funnel(results)
    if raw_funnel is None:
        return True, True, "skipped — raw_funnel not persisted"
    metrics = raw_funnel.get("stage_metrics")
    if not isinstance(metrics, list) or not metrics:
        return False, False, "raw_funnel.stage_metrics missing or empty"
    bad: list[str] = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            bad.append(f"#{index} (not an object)")
            continue
        entry_rate = _safe_float(metric.get("entry_rate"))
        drop_off_rate = _safe_float(metric.get("drop_off_rate"))
        agent_count = _safe_int(metric.get("agent_count"))
        if entry_rate is None or not (0.0 <= entry_rate <= 1.0):
            bad.append(f"#{index} entry_rate")
        if drop_off_rate is None or not (0.0 <= drop_off_rate <= 1.0):
            bad.append(f"#{index} drop_off_rate")
        if agent_count is not None and agent_count < 0:
            bad.append(f"#{index} agent_count")
    if bad:
        return (
            False,
            False,
            f"invalid stage metric(s): {', '.join(bad[:5])}",
        )
    return True, False, f"all {len(metrics)} stage metrics within bounds"


def _check_funnel_counts_monotonic(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    raw_funnel = _raw_funnel(results)
    if raw_funnel is None:
        return True, True, "skipped — raw_funnel not persisted"
    counts_raw = raw_funnel.get("stage_counts")
    if not isinstance(counts_raw, dict):
        return True, True, "skipped — stage_counts not persisted"
    counts = {str(k).upper(): _safe_int(v) for k, v in counts_raw.items()}
    sequence = [counts[stage] for stage in FUNNEL_ORDER if stage in counts]
    if len(sequence) < 2:
        return (
            True,
            True,
            "skipped — fewer than 2 ordered funnel stages present",
        )
    for prev, curr in zip(sequence, sequence[1:]):
        if prev is None or curr is None or curr > prev:
            stages = [s for s in FUNNEL_ORDER if s in counts][: len(sequence)]
            return (
                False,
                False,
                f"stage counts increase between {stages[0]} and {stages[-1]}: "
                f"{sequence}",
            )
    return True, False, f"stage counts non-increasing across {len(sequence)} stages"


def _check_domain_findings_present(
    results: dict[str, Any],
) -> tuple[bool, bool, str]:
    findings = results.get("domain_findings")
    if isinstance(findings, list) and findings:
        return True, False, f"{len(findings)} domain findings present"
    return False, False, "domain_findings missing or empty"


def _check_nan_inf_free(results: dict[str, Any]) -> tuple[bool, bool, str]:
    if _contains_non_finite(results):
        return False, False, "results contain NaN/Inf values"
    return True, False, "no NaN/Inf values detected"


# Check registry: (id, label, severity, runnable).
def _check_specs(
    expected_ids: list[str],
) -> list[tuple[str, str, str, Callable[[dict[str, Any]], tuple[bool, bool, str]]]]:
    return [
        ("results_present", "Results payload present", SEVERITY_CRITICAL, _check_results_present),
        (
            "top_level_rates_bounded",
            "Headline conversion within [0, 1]",
            SEVERITY_CRITICAL,
            _check_top_level_rates_bounded,
        ),
        (
            "agent_counts_consistent",
            "Agent counts consistent",
            SEVERITY_CRITICAL,
            _check_agent_counts_consistent,
        ),
        (
            "cluster_breakdown_present",
            "Cluster breakdown present",
            SEVERITY_CRITICAL,
            _check_cluster_breakdown_present,
        ),
        (
            "cluster_coverage",
            "Cluster coverage vs registry",
            SEVERITY_MAJOR,
            lambda results: _check_cluster_coverage(results, expected_ids),
        ),
        (
            "cluster_rates_bounded",
            "Cluster rates within [0, 1]",
            SEVERITY_CRITICAL,
            _check_cluster_rates_bounded,
        ),
        (
            "weighted_conversion_consistent",
            "Headline matches coverage-normalized blend",
            SEVERITY_MAJOR,
            lambda results: _check_weighted_consistency(results, expected_ids),
        ),
        (
            "funnel_metrics_bounded",
            "Funnel stage metrics within bounds",
            SEVERITY_MAJOR,
            _check_funnel_metrics_bounded,
        ),
        (
            "funnel_counts_monotonic",
            "Funnel stage counts non-increasing",
            SEVERITY_MAJOR,
            _check_funnel_counts_monotonic,
        ),
        (
            "domain_findings_present",
            "Domain findings generated",
            SEVERITY_MINOR,
            _check_domain_findings_present,
        ),
        ("nan_inf_free", "No NaN/Inf in results", SEVERITY_CRITICAL, _check_nan_inf_free),
    ]


_RECOMMENDATIONS: dict[str, str] = {
    "results_present": "Re-run the simulation — no results payload was persisted.",
    "top_level_rates_bounded": "Headline conversion is missing or out of range; the payload may be corrupted.",
    "agent_counts_consistent": "Converted count exceeds total agents; check funnel anchoring.",
    "cluster_breakdown_present": "No cluster-level breakdown persisted; check the conductor output.",
    "cluster_coverage": "Consumer clusters are missing from the breakdown; check sampling and cluster_parameters seeding.",
    "cluster_rates_bounded": "Cluster rates contain out-of-range or unparseable values; inspect cluster_breakdown.",
    "weighted_conversion_consistent": "Headline conversion diverges from the demand-weighted cluster blend; check funnel anchoring.",
    "funnel_metrics_bounded": "Funnel stage metrics contain invalid rates or negative counts.",
    "funnel_counts_monotonic": "Funnel stage counts increase between stages; check funnel chain construction.",
    "domain_findings_present": "No domain findings were generated; the accountability engine may have been skipped.",
    "nan_inf_free": "Results contain NaN/Inf values that will break downstream analytics.",
}


def _verdict(trust_score: float, has_critical_failure: bool) -> str:
    if has_critical_failure:
        # Critical integrity failures can never be a clean PASS — a founder
        # should review before acting on the headline numbers.
        return VERDICT_REVIEW if trust_score >= REVIEW_THRESHOLD else VERDICT_FAIL
    if trust_score >= PASS_THRESHOLD:
        return VERDICT_PASS
    if trust_score >= REVIEW_THRESHOLD:
        return VERDICT_REVIEW
    return VERDICT_FAIL


def build_simulation_quality(
    simulation_id: int,
    project_id: int,
    base_results: Any,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
) -> SimulationQualityOut:
    """
    Run the deterministic quality gate over a completed simulation's results.

    Pure post-hoc analysis — no Celery dispatch, no LLM calls, no DB writes.
    """
    results = _coerce_results(base_results)
    signal_quality = _safe_signal_quality(signal_quality)
    expected_ids = _expected_cluster_ids()

    checks: list[QualityCheck] = []
    for check_id, label, severity, runnable in _check_specs(expected_ids):
        passed, skipped, detail = runnable(results)
        checks.append(
            QualityCheck(
                id=check_id,
                label=label,
                severity=severity,
                passed=None if skipped else passed,
                skipped=skipped,
                detail=detail,
            )
        )

    evaluated = [c for c in checks if not c.skipped]
    total_weight = sum(
        SEVERITY_WEIGHTS.get(str(c.severity), 0.0) for c in evaluated
    )
    passed_weight = sum(
        SEVERITY_WEIGHTS.get(str(c.severity), 0.0)
        for c in evaluated
        if c.passed is True
    )
    trust_score = round(passed_weight / total_weight, 4) if total_weight > 0 else 0.0

    failed = [c for c in checks if not c.skipped and c.passed is not True]
    has_critical_failure = any(
        c.severity == SEVERITY_CRITICAL and c.passed is not True
        for c in failed
    )
    recommendations = [
        _RECOMMENDATIONS[c.id]
        for c in sorted(
            failed,
            key=lambda item: SEVERITY_WEIGHTS.get(str(item.severity), 0.0),
            reverse=True,
        )
        if c.id in _RECOMMENDATIONS
    ]

    headline = _headline_conversion(results)
    if headline is not None and not (0.0 <= headline <= 1.0):
        headline = None
    breakdown = results.get("cluster_breakdown")
    coverage_fraction = (
        _coverage_fraction(breakdown, expected_ids)
        if isinstance(breakdown, dict)
        else 0.0
    )

    summary = SimulationQualitySummary(
        total_checks=len(checks),
        evaluated_checks=len(evaluated),
        passed_checks=sum(1 for c in evaluated if c.passed is True),
        failed_checks=sum(1 for c in evaluated if c.passed is not True),
        skipped_checks=sum(1 for c in checks if c.skipped),
    )

    return SimulationQualityOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        trust_score=trust_score,
        verdict=_verdict(trust_score, has_critical_failure),
        headline_conversion=headline,
        signal_quality=(
            round(signal_quality, 4) if signal_quality is not None else None
        ),
        summary=summary,
        checks=checks,
        recommendations=recommendations,
        meta={
            "cluster_coverage_fraction": round(coverage_fraction, 4),
            "evaluated_checks": len(evaluated),
        },
    )


__all__ = ["build_simulation_quality"]

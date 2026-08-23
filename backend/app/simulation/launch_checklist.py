"""
Pure launch-checklist builder for completed simulation results.

Turns a completed run's persisted ``results_json``, signal quality,
assumption coverage and cluster coverage into a deterministic,
founder-facing readiness score. It answers "are these signals strong
enough to act on before launch?" without a Celery rerun or an LLM call.

Checks currently included:

* **Results present** — non-empty payload was persisted.
* **Headline conversion** — the population-weighted conversion survived
  persistence and is finite in [0, 1].
* **Cluster coverage** — the persisted breakdown covers at least 90% of
  the registered 52-cluster registry (>= 50% warns).
* **Signal quality** — the run's trust signal is >= 0.7 (PASS),
  >= 0.4 (WARN), otherwise FAIL.
* **Visible assumptions** — the project fed at least one visible
  assumption into the analysis; zero assumptions is a warning.
* **Funnel sanity** — ``raw_funnel`` stages are bounded and never
  increase from ARRIVE through DECIDE (missing legacy funnels are
  skipped, not failed).
* **Domain findings** — the accountability engine produced at least one
  finding; missing findings is a warning.

The readiness score is the share of evaluated check weight that passed,
with PASS = 1.0, WARN = 0.5 and FAIL = 0.0. Verdict bands are
``>= 0.80`` READY, ``>= 0.55`` NEEDS_WORK, otherwise NOT_READY. If no
check can be evaluated, the verdict is INSUFFICIENT_DATA.

No DB / I/O — verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.schemas.launch_checklist import (
    LaunchChecklistItem,
    LaunchChecklistOut,
    LaunchChecklistSummary,
)
from app.simulation.clusters.registry import ClusterRegistry

STATUS_PASS: str = "PASS"
STATUS_WARN: str = "WARN"
STATUS_FAIL: str = "FAIL"
STATUS_SKIP: str = "SKIP"

VERDICT_READY: str = "READY"
VERDICT_NEEDS_WORK: str = "NEEDS_WORK"
VERDICT_NOT_READY: str = "NOT_READY"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

READY_THRESHOLD: float = 0.80
NEEDS_WORK_THRESHOLD: float = 0.55

# Cluster coverage bands.
COVERAGE_PASS: float = 0.90
COVERAGE_WARN: float = 0.50

# Signal-quality bands.
SIGNAL_PASS: float = 0.70
SIGNAL_WARN: float = 0.40

# Funnel stages must be monotonically non-increasing from ARRIVE through
# DECIDE (PURCHASE is anchored to conversion, so it is exempt).
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
    the checklist nor inflate its score.
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


def _headline_conversion(results: dict[str, Any]) -> float | None:
    for key in ("population_weighted_conversion", "conversion_rate"):
        value = _safe_float(results.get(key))
        if value is not None:
            return value
    return _safe_float(results.get("mean_conversion_rate"))


def _expected_cluster_count() -> int:
    return len(ClusterRegistry().all_clusters())


def _coverage_fraction(
    breakdown: dict[str, Any] | None,
    expected_count: int,
) -> float:
    if expected_count <= 0:
        return 1.0
    if not isinstance(breakdown, dict):
        return 0.0
    present = sum(1 for _ in breakdown)
    return present / expected_count


def _funnel_is_sane(results: dict[str, Any]) -> tuple[bool, bool, str]:
    """Return (passed, skipped, detail) for the funnel check."""
    raw_funnel = results.get("raw_funnel")
    if not isinstance(raw_funnel, dict):
        return False, True, "raw_funnel missing from persisted results (legacy row)"
    previous: int | None = None
    for stage in FUNNEL_ORDER:
        raw = raw_funnel.get(stage)
        if raw is None:
            return False, True, f"raw_funnel.{stage} missing from persisted results"
        count = _safe_int(raw)
        if count is None or count < 0:
            return False, False, f"raw_funnel.{stage} is not a non-negative integer"
        if previous is not None and count > previous:
            return (
                False,
                False,
                f"raw_funnel.{stage} ({count}) exceeds {FUNNEL_ORDER[FUNNEL_ORDER.index(stage) - 1]} ({previous})",
            )
        previous = count
    return True, False, "funnel stages are bounded and monotonic through DECIDE"


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_contains_non_finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_non_finite(v) for v in value)
    return False


def build_launch_checklist(
    results: dict[str, Any] | None,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    visible_assumption_count: int | None = None,
    product_type: str = "saas",
    cluster_registry: list[dict[str, Any]] | None = None,
) -> LaunchChecklistOut:
    """Compose the launch-checklist read from completed results.

    Args:
        results: Simulation ``results_json``.
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
            Malformed values (NaN/Inf, out-of-range, non-numeric) are
            treated as missing rather than crashing the read.
        visible_assumption_count: Number of visible project assumptions
            available to the analysis.
        product_type: Detected product type for the run.
        cluster_registry: Optional registry entries
            (``{cluster_id, name, population_weight}``); when provided it
            is used for coverage, otherwise the canonical cluster registry
            is used.
    """
    payload = _coerce_results(results)
    signal_quality = _safe_signal_quality(signal_quality)
    product_type_name = str(
        product_type or payload.get("product_type_detected", "saas") or "saas"
    ).lower()

    expected_count = len(cluster_registry) if cluster_registry else _expected_cluster_count()
    breakdown = payload.get("cluster_breakdown")
    coverage = _coverage_fraction(breakdown, expected_count)

    items: list[LaunchChecklistItem] = []

    # 1. Results present.
    if payload:
        items.append(
            LaunchChecklistItem(
                id="results_present",
                category="data",
                label="Results payload present",
                status=STATUS_PASS,
                detail="Completed simulation persisted a non-empty results payload.",
                weight=1.0,
                score=1.0,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="results_present",
                category="data",
                label="Results payload present",
                status=STATUS_FAIL,
                detail="Completed simulation has an empty results payload.",
                weight=1.0,
                score=0.0,
            )
        )
    if not payload:
        return LaunchChecklistOut(
            simulation_id=simulation_id,
            project_id=project_id,
            status=status,
            product_type=product_type_name,
            readiness_score=0.0,
            verdict=VERDICT_NOT_READY,
            signal_quality=signal_quality,
            visible_assumptions=visible_assumption_count,
            summary=LaunchChecklistSummary(
                total_items=1,
                evaluated_items=1,
                passed_items=0,
                warned_items=0,
                failed_items=1,
                skipped_items=0,
            ),
            items=items,
            recommendations=[
                "Persisted signals are not launch-ready — re-run with a "
                "fuller environment and inspect why results were empty."
            ],
            meta={
                "expected_clusters": expected_count,
                "coverage": 0.0,
                "empty_results": True,
            },
        )

    # 2. Headline conversion.
    conversion = _headline_conversion(payload)
    if conversion is None:
        items.append(
            LaunchChecklistItem(
                id="headline_conversion",
                category="conversion",
                label="Headline conversion available",
                status=STATUS_FAIL,
                detail=(
                    "No population_weighted_conversion / conversion_rate / "
                    "mean_conversion_rate found."
                ),
                weight=1.0,
                score=0.0,
            )
        )
    elif 0.0 <= conversion <= 1.0:
        items.append(
            LaunchChecklistItem(
                id="headline_conversion",
                category="conversion",
                label="Headline conversion in range",
                status=STATUS_PASS,
                detail=f"Headline conversion is {conversion:.4f} within [0, 1].",
                weight=1.0,
                score=1.0,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="headline_conversion",
                category="conversion",
                label="Headline conversion in range",
                status=STATUS_FAIL,
                detail=f"Headline conversion {conversion:.6f} is outside [0, 1].",
                weight=1.0,
                score=0.0,
            )
        )

    # 3. Cluster coverage.
    if coverage >= COVERAGE_PASS:
        items.append(
            LaunchChecklistItem(
                id="cluster_coverage",
                category="coverage",
                label="Cluster coverage adequate",
                status=STATUS_PASS,
                detail=f"Persisted breakdown covers {coverage:.0%} of the expected registry.",
                weight=0.8,
                score=1.0,
            )
        )
    elif coverage >= COVERAGE_WARN:
        items.append(
            LaunchChecklistItem(
                id="cluster_coverage",
                category="coverage",
                label="Cluster coverage adequate",
                status=STATUS_WARN,
                detail=f"Persisted breakdown covers only {coverage:.0%} of the expected registry.",
                weight=0.8,
                score=0.5,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="cluster_coverage",
                category="coverage",
                label="Cluster coverage adequate",
                status=STATUS_FAIL,
                detail=f"Persisted breakdown covers {coverage:.0%} of the expected registry — material segments missing.",
                weight=0.8,
                score=0.0,
            )
        )

    # 4. Signal quality.
    if signal_quality is None:
        items.append(
            LaunchChecklistItem(
                id="signal_quality",
                category="trust",
                label="Simulation signal quality",
                status=STATUS_WARN,
                detail="No persisted signal quality is available.",
                weight=0.8,
                score=0.5,
            )
        )
    elif signal_quality >= SIGNAL_PASS:
        items.append(
            LaunchChecklistItem(
                id="signal_quality",
                category="trust",
                label="Simulation signal quality",
                status=STATUS_PASS,
                detail=f"Signal quality is {signal_quality:.2f}.",
                weight=0.8,
                score=1.0,
            )
        )
    elif signal_quality >= SIGNAL_WARN:
        items.append(
            LaunchChecklistItem(
                id="signal_quality",
                category="trust",
                label="Simulation signal quality",
                status=STATUS_WARN,
                detail=f"Signal quality is {signal_quality:.2f} — act with validation.",
                weight=0.8,
                score=0.5,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="signal_quality",
                category="trust",
                label="Simulation signal quality",
                status=STATUS_FAIL,
                detail=f"Signal quality is {signal_quality:.2f} — below the actionable floor.",
                weight=0.8,
                score=0.0,
            )
        )

    # 5. Visible assumptions.
    if visible_assumption_count is None or visible_assumption_count <= 0:
        items.append(
            LaunchChecklistItem(
                id="visible_assumptions",
                category="assumptions",
                label="Visible assumptions present",
                status=STATUS_WARN,
                detail="No visible assumptions fed the analysis; add project assumptions to sharpen signals.",
                weight=0.5,
                score=0.5,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="visible_assumptions",
                category="assumptions",
                label="Visible assumptions present",
                status=STATUS_PASS,
                detail=f"{visible_assumption_count} visible assumption(s) fed the analysis.",
                weight=0.5,
                score=1.0,
            )
        )

    # 6. Funnel sanity.
    funnel_passed, funnel_skipped, funnel_detail = _funnel_is_sane(payload)
    if funnel_skipped:
        items.append(
            LaunchChecklistItem(
                id="funnel_sanity",
                category="funnel",
                label="Funnel sanity",
                status=STATUS_SKIP,
                detail=funnel_detail,
                weight=0.0,
                score=0.0,
            )
        )
    elif funnel_passed:
        items.append(
            LaunchChecklistItem(
                id="funnel_sanity",
                category="funnel",
                label="Funnel sanity",
                status=STATUS_PASS,
                detail=funnel_detail,
                weight=0.6,
                score=1.0,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="funnel_sanity",
                category="funnel",
                label="Funnel sanity",
                status=STATUS_FAIL,
                detail=funnel_detail,
                weight=0.6,
                score=0.0,
            )
        )

    # 7. Domain findings present.
    findings = payload.get("domain_findings") or payload.get("findings")
    if findings:
        items.append(
            LaunchChecklistItem(
                id="domain_findings",
                category="accountability",
                label="Domain findings present",
                status=STATUS_PASS,
                detail="Accountability findings are available for review.",
                weight=0.5,
                score=1.0,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="domain_findings",
                category="accountability",
                label="Domain findings present",
                status=STATUS_WARN,
                detail="No domain findings found in persisted results.",
                weight=0.5,
                score=0.5,
            )
        )

    # 8. NaN/Inf free.
    non_finite_free = not _contains_non_finite(payload)
    if non_finite_free:
        items.append(
            LaunchChecklistItem(
                id="non_finite_free",
                category="data",
                label="Results free of NaN/Inf",
                status=STATUS_PASS,
                detail="Persisted results contain no NaN or infinite values.",
                weight=0.5,
                score=1.0,
            )
        )
    else:
        items.append(
            LaunchChecklistItem(
                id="non_finite_free",
                category="data",
                label="Results free of NaN/Inf",
                status=STATUS_FAIL,
                detail="Persisted results contain NaN or infinite values.",
                weight=0.5,
                score=0.0,
            )
        )

    summary = LaunchChecklistSummary()
    evaluated_weight = 0.0
    passed_weight = 0.0
    warned_weight = 0.0
    failed_weight = 0.0
    for item in items:
        summary.total_items += 1
        if item.status == STATUS_SKIP:
            summary.skipped_items += 1
            continue
        summary.evaluated_items += 1
        evaluated_weight += item.weight
        if item.status == STATUS_PASS:
            summary.passed_items += 1
            passed_weight += item.weight
        elif item.status == STATUS_WARN:
            summary.warned_items += 1
            warned_weight += item.weight
        else:
            summary.failed_items += 1
            failed_weight += item.weight

    if evaluated_weight <= 0.0:
        readiness_score = 0.0
        verdict = VERDICT_INSUFFICIENT
    else:
        readiness_score = (passed_weight + 0.5 * warned_weight) / evaluated_weight
        if readiness_score >= READY_THRESHOLD:
            verdict = VERDICT_READY
        elif readiness_score >= NEEDS_WORK_THRESHOLD:
            verdict = VERDICT_NEEDS_WORK
        else:
            verdict = VERDICT_NOT_READY

    recommendations: list[str] = []
    if verdict == VERDICT_READY:
        recommendations.append(
            "Signals look launch-actionable — proceed with your highest-ROI "
            "validation experiment while watching the weakest checklist item."
        )
    elif verdict == VERDICT_NEEDS_WORK:
        recommendations.append(
            "Signals are usable but not clean — fix the FAIL/WARN items "
            "before making irreversible launch decisions."
        )
    else:
        recommendations.append(
            "Persisted signals are not launch-ready — re-run with a fuller "
            "environment, add visible assumptions and re-check coverage."
        )
    if signal_quality is not None and signal_quality < SIGNAL_WARN:
        recommendations.append(
            f"Signal quality is low ({signal_quality:.2f}) — treat every "
            "projection as a hypothesis until validated with real demand."
        )
    if visible_assumption_count is None or visible_assumption_count <= 0:
        recommendations.append(
            "Add assumptions about your market, pricing, retention and "
            "post-purchase behavior so downstream reads have stronger inputs."
        )
    if coverage < COVERAGE_WARN:
        recommendations.append(
            "Cluster coverage is materially incomplete — re-run the "
            "simulation so the full consumer population is represented."
        )
    if not non_finite_free:
        recommendations.append(
            "Persisted results contain NaN/Inf values — re-run or repair "
            "the pipeline before treating any downstream projection as "
            "launch-ready."
        )

    meta: dict[str, Any] = {
        "expected_clusters": expected_count,
        "coverage": round(coverage, 4),
        "non_finite_free": non_finite_free,
        "thresholds": {
            "ready": READY_THRESHOLD,
            "needs_work": NEEDS_WORK_THRESHOLD,
            "signal_pass": SIGNAL_PASS,
            "signal_warn": SIGNAL_WARN,
            "coverage_pass": COVERAGE_PASS,
            "coverage_warn": COVERAGE_WARN,
        },
    }

    return LaunchChecklistOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=product_type_name,
        readiness_score=round(readiness_score, 4),
        verdict=verdict,
        signal_quality=signal_quality,
        visible_assumptions=visible_assumption_count,
        summary=summary,
        items=items,
        recommendations=recommendations,
        meta=meta,
    )


__all__ = [
    "COVERAGE_PASS",
    "COVERAGE_WARN",
    "NEEDS_WORK_THRESHOLD",
    "READY_THRESHOLD",
    "SIGNAL_PASS",
    "SIGNAL_WARN",
    "VERDICT_INSUFFICIENT",
    "VERDICT_NEEDS_WORK",
    "VERDICT_NOT_READY",
    "VERDICT_READY",
    "build_launch_checklist",
]

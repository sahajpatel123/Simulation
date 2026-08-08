"""
Validation experiment planner — turns validation-ROI rankings into a
concrete, sequenced validation sprint.

``build_validation_roi`` answers "which assumption should I validate first?".
This module answers the follow-up a founder actually asks: "what exactly do I
run, for how long, at what cost, and what tells me I'm right?". For every
assumption worth testing (``VALIDATE_FIRST`` / ``HIGH_VALUE`` tiers) it
selects a deterministic experiment method from the assumption's category,
then attaches cost tier, duration, sample target, success threshold and a
go/no-go rule.

Pure module — no DB, no I/O. Verifiable without FastAPI or PostgreSQL.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.validation_experiment import (
    ValidationExperiment,
    ValidationExperimentPlanOut,
    ValidationExperimentSummary,
)
from app.schemas.validation_roi import ValidationRoiOut
from app.simulation.validation_roi import (
    ROI_TIER_HIGH_VALUE,
    ROI_TIER_VALIDATE_FIRST,
)

# How many top de-risking assumptions get a planned experiment.
MAX_EXPERIMENTS: int = 5

_COST_RANK: dict[str, int] = {"FREE": 0, "LOW": 1, "MEDIUM": 2}

# Deterministic method specs. Thresholds are deliberately conservative
# defaults a first-time founder can use without prior benchmarks.
METHOD_SPECS: dict[str, dict[str, Any]] = {
    "LANDING_PAGE_SMOKE_TEST": {
        "label": "Landing-page smoke test",
        "description": (
            "Publish a focused landing page with the product, the price, and a "
            "single call-to-action; measure how many visitors request access or "
            "join a waitlist."
        ),
        "cost_tier": "LOW",
        "estimated_duration_days": 14,
        "sample_target": "300+ unique visitors",
        "success_metric": "signup / request rate",
        "success_threshold": "≥ 3% of unique visitors sign up (≥ 30 signups)",
        "go_no_go_rule": (
            "GO if signup rate ≥ 3%; iterate the landing message if 1–3%; "
            "challenge the demand assumption if < 1% after 300 visitors."
        ),
    },
    "CONCIERGE_MVP": {
        "label": "Concierge MVP test",
        "description": (
            "Manually deliver the core value to early users (spreadsheets, calls, "
            "or a hand-run service) and observe real behaviour instead of opinions."
        ),
        "cost_tier": "LOW",
        "estimated_duration_days": 14,
        "sample_target": "5–10 target users",
        "success_metric": "share of users with a second engagement or stated intent to pay",
        "success_threshold": "≥ 60%",
        "go_no_go_rule": (
            "GO if ≥ 60% return for a second engagement or express intent to pay; "
            "otherwise interview the drop-offs to find what is missing."
        ),
    },
    "WILLINGNESS_TO_PAY_SURVEY": {
        "label": "Willingness-to-pay survey",
        "description": (
            "Ask 30–50 target users a price-ladder / Van Westendorp question set "
            "to map demand at the planned price point."
        ),
        "cost_tier": "FREE",
        "estimated_duration_days": 7,
        "sample_target": "30–50 responses",
        "success_metric": "share willing to pay at the planned price",
        "success_threshold": "≥ 30%",
        "go_no_go_rule": (
            "GO if ≥ 30% would pay the planned price; re-test a lower price point "
            "if 15–30%; challenge the pricing assumption below 15%."
        ),
    },
    "COMPETITIVE_DESK_RESEARCH": {
        "label": "Competitive desk research",
        "description": (
            "Audit 10–20 comparable products for price, positioning, and whether "
            "they already serve the exact pain point you claim."
        ),
        "cost_tier": "FREE",
        "estimated_duration_days": 5,
        "sample_target": "10–20 comparable products",
        "success_metric": "share of comparable products priced at or above yours",
        "success_threshold": "≥ 50%",
        "go_no_go_rule": (
            "GO if ≥ 50% of comparable products price at or above yours; if none "
            "do, re-examine the positioning before building."
        ),
    },
    "PROTOTYPE_USABILITY_TEST": {
        "label": "Prototype usability test",
        "description": (
            "Run 5–8 target users through a clickable prototype of the core flow "
            "and watch where they stall."
        ),
        "cost_tier": "LOW",
        "estimated_duration_days": 10,
        "sample_target": "5–8 target users",
        "success_metric": "share of users completing the core flow unassisted",
        "success_threshold": "≥ 70%",
        "go_no_go_rule": (
            "GO if ≥ 70% complete the core flow unassisted; fix the top stall "
            "point and retest if lower."
        ),
    },
    "PRE_ORDER_WAITLIST": {
        "label": "Pre-order / waitlist test",
        "description": (
            "Offer a pre-order or waitlist with a deposit-or-nothing commitment "
            "to measure true demand rather than stated interest."
        ),
        "cost_tier": "LOW",
        "estimated_duration_days": 21,
        "sample_target": "100+ waitlist signups",
        "success_metric": "waitlist / pre-order rate",
        "success_threshold": "≥ 5% of visitors or 100 signups",
        "go_no_go_rule": (
            "GO if ≥ 5% convert or 100 signups arrive; otherwise the demand "
            "assumption needs a new angle before launch."
        ),
    },
    "PAID_ACQUISITION_TEST": {
        "label": "Paid acquisition test",
        "description": (
            "Run a small-budget paid campaign (US$100–300) to the landing page "
            "and measure acquisition cost and expressed interest."
        ),
        "cost_tier": "MEDIUM",
        "estimated_duration_days": 14,
        "sample_target": "500+ visitors",
        "success_metric": "click-through rate and cost per signup",
        "success_threshold": "CTR ≥ 2% and CAC ≤ 1 month of projected value",
        "go_no_go_rule": (
            "GO if CTR ≥ 2% and CAC stays within one month of projected value; "
            "cut spend and revisit positioning otherwise."
        ),
    },
    "USER_INTERVIEWS": {
        "label": "User interviews",
        "description": (
            "Run 5–10 structured interviews with target users to test the core "
            "pain point and willingness to change behaviour."
        ),
        "cost_tier": "FREE",
        "estimated_duration_days": 10,
        "sample_target": "5–10 interviews",
        "success_metric": "interviews surfacing a distinct, repeated pain point",
        "success_threshold": "≥ 3 of 5 (≥ 60%)",
        "go_no_go_rule": (
            "GO if ≥ 60% surface the same distinct pain point; if pain is diffuse, "
            "reframe the assumption before building."
        ),
    },
}


def _normalise_category(category: str) -> str:
    """Normalise an architect/category name for substring matching."""
    text = str(category or "").lower().replace("architect", "").strip()
    return text.replace("_", " ").replace("-", " ")


def _match_method(category: str, roi_tier: str) -> str:
    """Pick a deterministic experiment method from an assumption's category."""
    cat = _normalise_category(category)
    tokens = {t for t in cat.split() if t}
    if any(k in cat for k in ("pricing", "price", "willingness to pay", "cost")):
        return "WILLINGNESS_TO_PAY_SURVEY"
    if any(k in cat for k in ("market", "demand")) or tokens & {
        "tam",
        "sam",
        "som",
        "size",
    }:
        return "LANDING_PAGE_SMOKE_TEST"
    if any(
        k in cat
        for k in ("preorder", "pre order", "waitlist", "early access", "deposit")
    ):
        return "PRE_ORDER_WAITLIST"
    if any(k in cat for k in ("competit", "rival", "substitute")):
        return "COMPETITIVE_DESK_RESEARCH"
    if any(
        k in cat
        for k in ("acquisition", "channel", "distribution", "viral", "marketing", "advertis")
    ):
        return "PAID_ACQUISITION_TEST"
    if any(
        k in cat
        for k in (
            "retention",
            "support",
            "onboarding",
            "adoption",
            "feature",
            "setup",
            "aftersales",
            "lifecycle",
        )
    ):
        return "CONCIERGE_MVP"
    if "trust" in cat:
        return "USER_INTERVIEWS"
    if any(k in cat for k in ("usability", "performance", "prototype", "product")):
        return "PROTOTYPE_USABILITY_TEST"
    # Unknown category: prefer the cheapest demand signal for validate-first,
    # qualitative depth otherwise.
    if roi_tier == ROI_TIER_VALIDATE_FIRST:
        return "LANDING_PAGE_SMOKE_TEST"
    return "USER_INTERVIEWS"


def _tier_label(roi_tier: str) -> str:
    return "validate-first" if roi_tier == ROI_TIER_VALIDATE_FIRST else "high-value"


def _build_rationale(
    assumption_text: str,
    method: str,
    roi_tier: str,
    confidence_tier: str,
    validation_roi: float,
    expected_swing: float,
) -> str:
    spec = METHOD_SPECS[method]
    snippet = assumption_text[:80]
    return (
        f"'{snippet}' is {_tier_label(roi_tier)} (ROI {validation_roi:.2f}) at "
        f"{confidence_tier} confidence, and closing its gap could move conversion "
        f"by up to {expected_swing:.1%}. A {spec['label'].lower()} is "
        f"{_cost_evidence_phrase(spec['cost_tier'])} you can collect before launch."
    )


def _cost_evidence_phrase(cost_tier: str) -> str:
    """Honest cost phrasing for the rationale (MEDIUM tests are not 'cheapest')."""
    if cost_tier == "FREE":
        return "the cheapest direct evidence"
    if cost_tier == "LOW":
        return "a low-cost, direct piece of evidence"
    return "the most direct evidence"


def _build_experiment(row, method: str) -> ValidationExperiment:
    spec = METHOD_SPECS[method]
    return ValidationExperiment(
        assumption_text=row.assumption_text,
        category=row.category,
        roi_tier=row.roi_tier,
        validation_roi=row.validation_roi,
        expected_conversion_swing=row.expected_conversion_swing,
        confidence_tier=row.confidence_tier,
        method=method,
        method_label=spec["label"],
        method_description=spec["description"],
        cost_tier=spec["cost_tier"],
        estimated_duration_days=spec["estimated_duration_days"],
        sample_target=spec["sample_target"],
        success_metric=spec["success_metric"],
        success_threshold=spec["success_threshold"],
        go_no_go_rule=spec["go_no_go_rule"],
        rationale=_build_rationale(
            assumption_text=row.assumption_text,
            method=method,
            roi_tier=row.roi_tier,
            confidence_tier=row.confidence_tier,
            validation_roi=row.validation_roi,
            expected_swing=row.expected_conversion_swing,
        ),
    )


def _build_summary(
    experiments: list[ValidationExperiment],
) -> ValidationExperimentSummary:
    if not experiments:
        return ValidationExperimentSummary(
            experiment_count=0,
            budget_ceiling="FREE",
        )
    counts = {"FREE": 0, "LOW": 0, "MEDIUM": 0}
    for exp in experiments:
        counts[exp.cost_tier] += 1
    top_cost = max(
        (exp.cost_tier for exp in experiments), key=lambda c: _COST_RANK[c]
    )
    return ValidationExperimentSummary(
        experiment_count=len(experiments),
        validate_first_count=sum(
            1 for exp in experiments if exp.roi_tier == ROI_TIER_VALIDATE_FIRST
        ),
        high_value_count=sum(
            1 for exp in experiments if exp.roi_tier == ROI_TIER_HIGH_VALUE
        ),
        free_count=counts["FREE"],
        low_cost_count=counts["LOW"],
        medium_cost_count=counts["MEDIUM"],
        sprint_days=max(exp.estimated_duration_days for exp in experiments),
        sequential_days=sum(exp.estimated_duration_days for exp in experiments),
        budget_ceiling=top_cost,
        top_experiment=experiments[0].method_label,
    )


def _build_narrative(
    experiments: list[ValidationExperiment],
    summary: ValidationExperimentSummary,
) -> str:
    if not experiments:
        return (
            "No assumptions currently need an experiment: the ones worth testing "
            "are either already validated or have minimal conversion impact. "
            "Track early-user feedback after launch and re-run validation-ROI "
            "when assumptions change."
        )
    top = experiments[0]
    snippet = top.assumption_text[:80]
    return (
        f"{_sprint_window_label(summary.sprint_days)} validation sprint: "
        f"{summary.experiment_count} experiments, "
        f"starting with {summary.top_experiment.lower()} for '{snippet}' "
        f"(ROI {top.validation_roi:.2f}). Run in parallel they fit in about "
        f"{summary.sprint_days} days with a {summary.budget_ceiling.lower()} "
        "budget ceiling; each has an explicit go/no-go rule."
    )


def _sprint_window_label(sprint_days: int) -> str:
    """Label the sprint window from its parallel duration (max experiment)."""
    if sprint_days <= 7:
        return "Week-1"
    if sprint_days <= 14:
        return "two-week"
    if sprint_days <= 21:
        return "three-week"
    return "multi-week"


def build_validation_experiment_plan(
    roi: ValidationRoiOut,
    *,
    max_experiments: int = MAX_EXPERIMENTS,
) -> ValidationExperimentPlanOut:
    """
    Build a concrete validation experiment plan from a validation-ROI ranking.

    Only ``VALIDATE_FIRST`` and ``HIGH_VALUE`` assumptions receive experiments;
    lower tiers are already de-risked or too low-impact to spend time on.
    Experiments keep the ROI ranking order and are capped at ``max_experiments``.
    Rows sharing the same assumption text are deduplicated (the strongest ROI
    row wins), blank assumption texts are skipped, and ``max_experiments``
    below 1 yields an empty plan.
    """
    limit = max(0, int(max_experiments))
    experiments: list[ValidationExperiment] = []
    ranked = sorted(
        roi.assumptions,
        key=lambda r: (-r.validation_roi, -r.sensitivity_score, -abs(r.max_delta)),
    )
    seen_texts: set[str] = set()
    for row in ranked:
        if row.roi_tier not in (ROI_TIER_VALIDATE_FIRST, ROI_TIER_HIGH_VALUE):
            continue
        if len(experiments) >= limit:
            break
        text_key = (row.assumption_text or "").strip()
        if not text_key or text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        method = _match_method(row.category, row.roi_tier)
        experiments.append(_build_experiment(row, method))

    summary = _build_summary(experiments)
    return ValidationExperimentPlanOut(
        simulation_id=roi.simulation_id,
        project_id=roi.project_id,
        status=roi.status,
        baseline_conversion=roi.baseline_conversion,
        signal_quality=roi.signal_quality,
        summary=summary,
        experiments=experiments,
        narrative=_build_narrative(experiments, summary),
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "validation_experiment_planner_v1",
            "source": "validation_roi_v1 ranking (sensitivity x uncertainty)",
            "method_mapping": "category-driven with deterministic per-method specs",
            "success_thresholds": "conservative defaults; founders should replace "
            "with product-specific benchmarks when available",
            "planned_tiers": [ROI_TIER_VALIDATE_FIRST, ROI_TIER_HIGH_VALUE],
            "max_experiments": limit,
        },
    )


__all__ = [
    "MAX_EXPERIMENTS",
    "METHOD_SPECS",
    "build_validation_experiment_plan",
]

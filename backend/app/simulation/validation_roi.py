"""
Pure validation-ROI ("de-risking priority") analysis for completed simulations.

Sensitivity analysis answers "which assumption moves my conversion the most?".
This module adds the second axis a founder actually spends money on: *how well
validated is that assumption today?* An assumption with a huge conversion swing
but backed by real evidence is already de-risked; an assumption with a modest
swing and no evidence can still be the best next validation experiment.

For each assumption:

* ``confidence_score`` — 0..1 backing strength, from the same claim-confidence
  taxonomy the signal-quality pipeline uses (``VALIDATED_EXTERNAL`` = 1.0,
  ``VALIDATED_INTERNAL`` = 0.75, ``DESIGN_INTENT`` = 0.55,
  ``ASPIRATIONAL`` = 0.40). Explicit ``claim_confidence`` values on assumption
  dicts win over the text heuristic when they rank higher.
* ``validation_roi`` — ``sensitivity_score x (1 - confidence_score)``,
  normalised 0..1. The expected value of closing the uncertainty gap.
* ``expected_conversion_swing`` — ``|max_delta| x (1 - confidence_score)``,
  the conversion movement validation could unlock (or prevent).

No DB / I/O — verifiable without FastAPI or PostgreSQL. The Markov math is
delegated to :func:`app.simulation.sensitivity_analysis.build_sensitivity_analysis`
so the transition engine stays in one place.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.validation_roi import (
    AssumptionValidationRoi,
    ValidationRoiOut,
    ValidationRoiSummary,
)
from app.simulation.scored_assumption import (
    CONFIDENCE_MULTIPLIERS,
    ClaimConfidence,
    classify_confidence,
)
from app.simulation.sensitivity_analysis import build_sensitivity_analysis

# Validation-ROI tier thresholds. ROI lives in [0, 0.6] in practice
# (sensitivity 0..1 x uncertainty 0..0.6), so the bands below separate
# "go validate now" from "nice to know" without false alarms.
VALIDATE_FIRST_MIN: float = 0.30
HIGH_VALUE_MIN: float = 0.15
MONITOR_MIN: float = 0.05

ROI_TIER_VALIDATE_FIRST: str = "VALIDATE_FIRST"
ROI_TIER_HIGH_VALUE: str = "HIGH_VALUE"
ROI_TIER_MONITOR: str = "MONITOR"
ROI_TIER_LOW_VALUE: str = "LOW_VALUE"

# How many top de-risking recommendations to surface in the response.
MAX_RECOMMENDATIONS: int = 3

# Claim-confidence tiers counted as "already validated".
VALIDATED_TIERS: frozenset[str] = frozenset(
    {ClaimConfidence.VALIDATED_EXTERNAL.value, ClaimConfidence.VALIDATED_INTERNAL.value}
)

# Rank map used to merge explicit claim_confidence with the text heuristic.
# Kept in parity with ``scored_assumption._CONFIDENCE_RANK`` so a persisted
# override always wins when it represents stronger evidence.
_CONFIDENCE_RANK: dict[ClaimConfidence, int] = {
    ClaimConfidence.ASPIRATIONAL: 0,
    ClaimConfidence.DESIGN_INTENT: 1,
    ClaimConfidence.VALIDATED_INTERNAL: 2,
    ClaimConfidence.VALIDATED_EXTERNAL: 3,
}


def _parse_confidence(raw: Any) -> ClaimConfidence | None:
    """Parse a persisted claim_confidence value into the enum (or ``None``)."""
    if isinstance(raw, ClaimConfidence):
        return raw
    if raw is None or not str(raw).strip():
        return None
    try:
        return ClaimConfidence(str(raw).strip().upper().replace(" ", "_"))
    except ValueError:
        return None


def _assumption_meta(existing_assumptions: list[Any]) -> dict[str, dict[str, Any]]:
    """Map assumption text -> merged metadata (category, explicit confidence).

    The same claim text can appear multiple times (re-extracted by another
    architect, or a user-updated copy). Metadata is merged per text: the first
    non-empty category wins and the strongest explicit ``claim_confidence``
    wins, so a persisted override is never silently dropped.
    """
    meta: dict[str, dict[str, Any]] = {}
    for a in existing_assumptions or []:
        if isinstance(a, dict):
            text = str(a.get("text", a.get("assumption", "")))
            category = str(a.get("category", ""))
            raw_confidence = a.get("claim_confidence")
        else:
            text = str(getattr(a, "text", ""))
            category = str(getattr(a, "category", "") or "")
            raw_confidence = getattr(a, "claim_confidence", None)
        if not text:
            continue
        entry = meta.setdefault(text, {"category": "", "claim_confidence": None})
        if not entry["category"] and category:
            entry["category"] = category
        parsed = _parse_confidence(raw_confidence)
        if parsed is not None:
            current = entry["claim_confidence"]
            if current is None or _CONFIDENCE_RANK[parsed] > _CONFIDENCE_RANK[current]:
                entry["claim_confidence"] = parsed
    return meta


def _resolve_confidence(text: str, extra_raw: Any) -> tuple[ClaimConfidence, float]:
    """Combine the text heuristic with an optional explicit claim_confidence."""
    confidence = classify_confidence(text)
    parsed = _parse_confidence(extra_raw)
    if parsed is not None and _CONFIDENCE_RANK[parsed] > _CONFIDENCE_RANK[confidence]:
        confidence = parsed
    return confidence, CONFIDENCE_MULTIPLIERS[confidence]


def _roi_tier(roi: float) -> str:
    """Map a normalised validation-ROI score to a tier label."""
    if roi >= VALIDATE_FIRST_MIN:
        return ROI_TIER_VALIDATE_FIRST
    if roi >= HIGH_VALUE_MIN:
        return ROI_TIER_HIGH_VALUE
    if roi >= MONITOR_MIN:
        return ROI_TIER_MONITOR
    return ROI_TIER_LOW_VALUE


def _build_recommendation(
    text: str,
    roi_tier: str,
    confidence_tier: str,
    expected_swing: float,
) -> str:
    """Generate a founder-facing action for an assumption's ROI tier."""
    snippet = text[:80]
    if roi_tier == ROI_TIER_VALIDATE_FIRST:
        return (
            f"VALIDATE FIRST: '{snippet}' is only {confidence_tier} confidence yet can "
            f"swing conversion by up to {expected_swing:.1%}. Run a landing-page test "
            "or 5-10 user interviews before launch."
        )
    if roi_tier == ROI_TIER_HIGH_VALUE:
        return (
            f"HIGH VALUE: validating '{snippet}' (currently {confidence_tier}) could "
            f"move conversion up to {expected_swing:.1%}. Prioritise a cheap experiment."
        )
    if roi_tier == ROI_TIER_MONITOR:
        return (
            f"MONITOR: '{snippet}' is {confidence_tier} confidence with a "
            f"{expected_swing:.1%} possible swing. Track early-user feedback; "
            "no dedicated test needed yet."
        )
    if confidence_tier in VALIDATED_TIERS:
        return (
            f"LOW VALUE: '{snippet}' is already {confidence_tier} with minimal "
            "conversion impact. Safe to leave as-is."
        )
    return (
        f"LOW VALUE: '{snippet}' has minimal conversion impact. Safe to leave "
        "as-is even though it is not yet validated."
    )


def _build_narrative(summary: ValidationRoiSummary) -> str:
    """One-paragraph founder-facing summary of the analysis."""
    if summary.total_assumptions == 0:
        return (
            "No assumptions found for this project. Add assumptions to enable "
            "validation-ROI analysis."
        )
    if summary.top_de_risking_assumption:
        return (
            f"{summary.validate_first_count} of {summary.total_assumptions} assumptions "
            f"are validate-first. Start with '{summary.top_de_risking_assumption[:80]}' "
            f"(ROI {summary.top_roi_score:.2f}) — closing its uncertainty could move "
            f"conversion by up to {summary.top_expected_swing:.1%}."
        )
    return (
        f"All {summary.total_assumptions} assumptions are low-validation-value: "
        "either already validated or with minimal conversion impact."
    )


def build_validation_roi(
    simulation_id: int,
    project_id: int,
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    signal_quality: float | None = None,
) -> ValidationRoiOut:
    """
    Build a validation-ROI ranking from a completed simulation.

    Composes the existing sensitivity engine (per-assumption conversion swing)
    with claim-confidence scoring (per-assumption backing strength). Output is
    ranked by validation ROI, highest first.
    """
    sensitivity = build_sensitivity_analysis(
        simulation_id=simulation_id,
        project_id=project_id,
        base_results=base_results,
        env_params=env_params,
        existing_assumptions=existing_assumptions,
    )
    meta_by_text = _assumption_meta(existing_assumptions)

    rows: list[AssumptionValidationRoi] = []
    for item in sensitivity.assumptions:
        meta = meta_by_text.get(item.assumption_text, {})
        confidence_enum, confidence_score = _resolve_confidence(
            item.assumption_text, meta.get("claim_confidence")
        )
        uncertainty = round(max(0.0, min(1.0, 1.0 - confidence_score)), 4)
        roi = round(
            max(0.0, min(1.0, item.sensitivity_score * uncertainty)), 4
        )
        expected_swing = round(abs(item.max_delta) * uncertainty, 6)
        tier = _roi_tier(roi)
        rows.append(
            AssumptionValidationRoi(
                assumption_text=item.assumption_text,
                category=str(meta.get("category", "")),
                sensitivity_tier=item.sensitivity_tier,
                sensitivity_score=item.sensitivity_score,
                max_delta=item.max_delta,
                confidence_tier=confidence_enum.value,
                confidence_score=confidence_score,
                validation_roi=roi,
                roi_tier=tier,
                expected_conversion_swing=expected_swing,
                recommendation=_build_recommendation(
                    text=item.assumption_text,
                    roi_tier=tier,
                    confidence_tier=confidence_enum.value,
                    expected_swing=expected_swing,
                ),
            )
        )

    rows.sort(
        key=lambda r: (-r.validation_roi, -r.sensitivity_score, -abs(r.max_delta))
    )

    if rows:
        avg_confidence = round(
            sum(r.confidence_score for r in rows) / len(rows), 4
        )
        validated_count = sum(1 for r in rows if r.confidence_tier in VALIDATED_TIERS)
        validate_first_count = sum(
            1 for r in rows if r.roi_tier == ROI_TIER_VALIDATE_FIRST
        )
        high_value_count = sum(1 for r in rows if r.roi_tier == ROI_TIER_HIGH_VALUE)
        monitor_count = sum(1 for r in rows if r.roi_tier == ROI_TIER_MONITOR)
        low_value_count = sum(1 for r in rows if r.roi_tier == ROI_TIER_LOW_VALUE)
        top = rows[0]
        summary = ValidationRoiSummary(
            total_assumptions=len(rows),
            baseline_conversion=sensitivity.baseline_conversion,
            avg_confidence=avg_confidence,
            validated_assumptions=validated_count,
            unvalidated_assumptions=len(rows) - validated_count,
            validate_first_count=validate_first_count,
            high_value_count=high_value_count,
            monitor_count=monitor_count,
            low_value_count=low_value_count,
            top_de_risking_assumption=top.assumption_text[:200],
            top_roi_score=top.validation_roi,
            top_expected_swing=top.expected_conversion_swing,
        )
    else:
        summary = ValidationRoiSummary(
            total_assumptions=0,
            baseline_conversion=sensitivity.baseline_conversion,
        )

    recs = [r.recommendation for r in rows[:MAX_RECOMMENDATIONS]]
    if not recs:
        recs = list(sensitivity.recommendations)

    sq = sensitivity.signal_quality
    if sq is None:
        sq = signal_quality

    return ValidationRoiOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status="COMPLETED",
        baseline_conversion=sensitivity.baseline_conversion,
        signal_quality=sq,
        summary=summary,
        assumptions=rows,
        recommendations=recs,
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "validation_roi_v1",
            "confidence_source": (
                "text-heuristic classify_confidence, overridden by explicit "
                "claim_confidence when it ranks higher"
            ),
            "roi_formula": "sensitivity_score x (1 - confidence_score)",
            "tier_thresholds": {
                "VALIDATE_FIRST_MIN": VALIDATE_FIRST_MIN,
                "HIGH_VALUE_MIN": HIGH_VALUE_MIN,
                "MONITOR_MIN": MONITOR_MIN,
            },
            "assumption_count": len(rows),
        },
    )


__all__ = [
    "build_validation_roi",
    "VALIDATE_FIRST_MIN",
    "HIGH_VALUE_MIN",
    "MONITOR_MIN",
    "ROI_TIER_VALIDATE_FIRST",
    "ROI_TIER_HIGH_VALUE",
    "ROI_TIER_MONITOR",
    "ROI_TIER_LOW_VALUE",
]

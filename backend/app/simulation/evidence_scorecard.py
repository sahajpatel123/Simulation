"""
De-risking scorecard engine — turns logged validation experiments into
confidence upgrades/downgrades and shows how the validation-ROI ranking
shifts for one assumption.

The pipeline is: validation-ROI says *which* assumption to validate first,
the experiment planner says *what* to run, and this module closes the loop
by turning a recorded ``PASS`` / ``FAIL`` / ``INCONCLUSIVE`` result into an
evidence-derived confidence tier that feeds back into the same ROI formula
``sensitivity x (1 - confidence)``.

Evidence → confidence mapping (deterministic, deliberately conservative):

* ``PASS``         → ``VALIDATED_INTERNAL`` (founder-run test succeeded).
                    Stronger existing evidence (``VALIDATED_EXTERNAL``) is
                    never downgraded by a single passing test.
* ``FAIL``         → ``ASPIRATIONAL`` (the claim was contradicted; treat it
                    as hope until reworked and re-tested).
* ``INCONCLUSIVE`` → no change (insufficient signal).

The most recent *decisive* result (PASS/FAIL) wins; a trailing
INCONCLUSIVE does not erase an earlier decisive outcome.

Pure module — no DB, no I/O. Reuses ``build_validation_roi`` so the ROI
math and tier thresholds stay in one place.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.assumption_evidence import (
    AssumptionEvidenceScorecardOut,
    EvidenceOut,
)
from app.schemas.validation_roi import CONFIDENCE_TIER_LITERAL
from app.simulation.scored_assumption import (
    CONFIDENCE_MULTIPLIERS,
    ClaimConfidence,
)
from app.simulation.validation_experiment_planner import METHOD_SPECS
from app.simulation.validation_roi import _roi_tier, build_validation_roi

EVIDENCE_RESULT_PASS: str = "PASS"
EVIDENCE_RESULT_FAIL: str = "FAIL"
EVIDENCE_RESULT_INCONCLUSIVE: str = "INCONCLUSIVE"

DECISIVE_RESULTS: frozenset[str] = frozenset(
    {EVIDENCE_RESULT_PASS, EVIDENCE_RESULT_FAIL}
)

# Confidence tier strength, kept in parity with scored_assumption and
# validation_roi so PASS can "never downgrade stronger evidence".
_TIER_RANK: dict[str, int] = {
    "ASPIRATIONAL": 0,
    "DESIGN_INTENT": 1,
    "VALIDATED_INTERNAL": 2,
    "VALIDATED_EXTERNAL": 3,
}


def derive_confidence(result: str) -> ClaimConfidence | None:
    """Map an experiment result to the confidence tier it implies.

    Comparison is case/whitespace-insensitive so legacy rows that stored
    ``"pass"`` or ``" FAIL "`` still count as decisive evidence instead of
    silently falling through to the INCONCLUSIVE path.
    """
    normalized = str(result or "").strip().upper()
    if normalized == EVIDENCE_RESULT_PASS:
        return ClaimConfidence.VALIDATED_INTERNAL
    if normalized == EVIDENCE_RESULT_FAIL:
        return ClaimConfidence.ASPIRATIONAL
    return None


def _tier_rank(tier: str) -> int:
    return _TIER_RANK.get(str(tier).strip().upper(), 1)


def _effective_confidence(before_tier: str, result: str) -> tuple[str, float]:
    """Combine the heuristic tier with an experiment result.

    PASS never downgrades stronger existing evidence; FAIL always drops the
    claim to ASPIRATIONAL; INCONCLUSIVE leaves the tier untouched.
    """
    derived = derive_confidence(result)
    if derived is None:
        return before_tier, CONFIDENCE_MULTIPLIERS[ClaimConfidence(before_tier)]
    if derived == ClaimConfidence.VALIDATED_INTERNAL and _tier_rank(
        before_tier
    ) > _tier_rank(derived.value):
        return before_tier, CONFIDENCE_MULTIPLIERS[ClaimConfidence(before_tier)]
    return derived.value, CONFIDENCE_MULTIPLIERS[derived]


def _as_utc(value: Any) -> datetime:
    """Coerce a timestamp to an aware UTC datetime for safe comparison."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _evidence_sort_key(row: Any) -> tuple[Any, int]:
    return (_as_utc(getattr(row, "created_at", None)), int(getattr(row, "id", 0) or 0))


def _method_label(method: str) -> str:
    spec = METHOD_SPECS.get(str(method or ""))
    return str(spec.get("label", "")) if spec else str(method or "")


def evidence_to_out(row: Any, assumption_text: str) -> EvidenceOut:
    """Serialise one evidence ORM row (or fake) into an ``EvidenceOut``."""
    method = str(getattr(row, "method", "") or "")
    result = str(getattr(row, "result", "") or "")
    derived = derive_confidence(result)
    return EvidenceOut(
        id=int(getattr(row, "id", 0) or 0),
        project_id=int(getattr(row, "project_id", 0) or 0),
        assumption_id=int(getattr(row, "assumption_id", 0) or 0),
        assumption_text=assumption_text,
        method=method,
        method_label=_method_label(method),
        result=result,
        observed_metric=getattr(row, "observed_metric", None),
        notes=getattr(row, "notes", None),
        created_at=getattr(row, "created_at", None),
        derived_confidence=derived.value if derived is not None else None,
    )


def _latest_decisive(history: list[EvidenceOut]) -> EvidenceOut | None:
    for row in history:  # already most-recent first
        if str(row.result or "").strip().upper() in DECISIVE_RESULTS:
            return row
    return None


def _recommendation(
    snippet: str,
    decisive: EvidenceOut | None,
    most_recent: EvidenceOut | None,
    derived: ClaimConfidence | None,
    before_roi: float | None,
    after_roi: float | None,
    after_tier: str | None = None,
    after_roi_tier: str | None = None,
) -> str:
    if decisive is None:
        if most_recent is not None:
            return (
                f"INCONCLUSIVE: the latest "
                f"{_method_label(most_recent.method).lower() or 'experiment'} "
                f"did not settle '{snippet}' — rerun with a larger sample or a "
                "different method."
            )
        return (
            f"No validation experiments logged for '{snippet}' yet. Use the "
            "validation-experiment plan to run a concrete first test."
        )
    method = _method_label(decisive.method).lower() or "experiment"
    if derived == ClaimConfidence.VALIDATED_INTERNAL:
        if before_roi is not None and after_roi is not None and after_roi < before_roi:
            return (
                f"PASS: '{snippet}' was confirmed by a {method} — confidence is now "
                f"{after_tier or derived.value}, and validation-ROI fell from "
                f"{before_roi:.3f} to {after_roi:.3f}."
            )
        if before_roi is not None and after_roi is not None:
            # Stronger evidence already existed — the tier (and ROI) did not move.
            return (
                f"PASS: '{snippet}' was confirmed again by a {method} — confidence "
                f"stays {after_tier or derived.value} (already backed by stronger "
                f"evidence), so validation-ROI is unchanged at {before_roi:.3f}."
            )
        return (
            f"PASS: '{snippet}' was confirmed by a {method} — recorded as "
            f"{derived.value} evidence."
        )
    if derived == ClaimConfidence.ASPIRATIONAL:
        if before_roi is not None and after_roi is not None and after_roi > before_roi:
            return (
                f"FAIL: '{snippet}' was contradicted by a {method} — treat it as "
                "ASPIRATIONAL and rework or replace it before building"
                + (
                    f" (de-risking priority rose to {after_roi_tier})."
                    if after_roi_tier
                    else "."
                )
            )
        return (
            f"FAIL: '{snippet}' was contradicted by a {method} — treat it as "
            "ASPIRATIONAL and rework or replace it before building."
        )
    return (
        f"INCONCLUSIVE: the latest {method} did not settle '{snippet}' — rerun "
        "with a larger sample or a different method."
    )


def build_assumption_scorecard(
    *,
    simulation_id: int,
    project_id: int,
    assumption: Any,
    evidence: list[Any],
    base_results: dict[str, Any],
    env_params: dict[str, Any],
    existing_assumptions: list[Any],
    signal_quality: float | None = None,
) -> AssumptionEvidenceScorecardOut:
    """Build a de-risking scorecard for a single assumption.

    Reuses :func:`app.simulation.validation_roi.build_validation_roi` for the
    baseline analysis, then recomputes the same ``sensitivity x uncertainty``
    formula with the evidence-derived confidence tier to show the ROI shift.
    """
    text = str(getattr(assumption, "text", "") or "")
    category = str(getattr(assumption, "category", "") or "")
    sensitivity = str(getattr(assumption, "sensitivity", "") or "")
    assumption_id = int(getattr(assumption, "id", 0) or 0)

    history = [
        evidence_to_out(row, text)
        for row in sorted(evidence, key=_evidence_sort_key, reverse=True)
    ]
    decisive = _latest_decisive(history)
    most_recent = history[0] if history else None
    derived = derive_confidence(decisive.result) if decisive is not None else None

    roi = build_validation_roi(
        simulation_id=simulation_id,
        project_id=project_id,
        base_results=base_results,
        env_params=env_params,
        existing_assumptions=existing_assumptions,
        signal_quality=signal_quality,
    )
    row = next((r for r in roi.assumptions if r.assumption_text == text), None)

    if row is None:
        return AssumptionEvidenceScorecardOut(
            project_id=project_id,
            assumption_id=assumption_id,
            assumption_text=text,
            category=category,
            sensitivity=sensitivity,
            evidence_count=len(history),
            latest_result=most_recent.result if most_recent else None,
            derived_confidence=derived.value if derived is not None else None,
            recommendation=_recommendation(
                text[:80], decisive, most_recent, derived, None, None, None
            ),
            history=history,
            meta=_meta(),
        )

    before_tier: CONFIDENCE_TIER_LITERAL = row.confidence_tier
    before_roi = row.validation_roi
    before_roi_tier = row.roi_tier

    if derived is None:
        after_tier, after_score = _effective_confidence(before_tier, "INCONCLUSIVE")
        after_roi = before_roi
        after_roi_tier = before_roi_tier
    else:
        after_tier, after_score = _effective_confidence(before_tier, decisive.result)
        uncertainty = round(max(0.0, min(1.0, 1.0 - after_score)), 4)
        after_roi = round(
            max(0.0, min(1.0, row.sensitivity_score * uncertainty)), 4
        )
        after_roi_tier = _roi_tier(after_roi)

    roi_delta = round(after_roi - before_roi, 4)
    tier_upgraded = after_roi_tier != before_roi_tier

    return AssumptionEvidenceScorecardOut(
        project_id=project_id,
        assumption_id=assumption_id,
        assumption_text=text,
        category=category,
        sensitivity=sensitivity,
        evidence_count=len(history),
        latest_result=most_recent.result if most_recent else None,
        derived_confidence=derived.value if derived is not None else None,
        confidence_before=before_tier,
        confidence_after=after_tier,
        validation_roi_before=before_roi,
        validation_roi_after=after_roi,
        roi_tier_before=before_roi_tier,
        roi_tier_after=after_roi_tier,
        roi_delta=roi_delta,
        tier_upgraded=tier_upgraded,
        recommendation=_recommendation(
            text[:80],
            decisive,
            most_recent,
            derived,
            before_roi,
            after_roi,
            after_tier,
            after_roi_tier,
        ),
        history=history,
        meta=_meta(),
    )


def _meta() -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": "evidence_scorecard_v1",
        "evidence_mapping": {
            EVIDENCE_RESULT_PASS: (
                "VALIDATED_INTERNAL (never downgrades stronger existing evidence)"
            ),
            EVIDENCE_RESULT_FAIL: "ASPIRATIONAL",
            EVIDENCE_RESULT_INCONCLUSIVE: "no change",
        },
        "roi_formula": "sensitivity_score x (1 - confidence_score)",
        "decisive_result_policy": "most recent PASS/FAIL wins; INCONCLUSIVE is ignored",
    }


__all__ = [
    "EVIDENCE_RESULT_PASS",
    "EVIDENCE_RESULT_FAIL",
    "EVIDENCE_RESULT_INCONCLUSIVE",
    "derive_confidence",
    "evidence_to_out",
    "build_assumption_scorecard",
]

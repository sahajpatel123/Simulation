"""
Evidence-verdicts scorecard: judge logged evidence against each method's bar.

The validation-experiment planner gives every method an explicit success
threshold (``METHOD_SPECS[...]["success_threshold"]``, e.g. "≥ 30% would
pay the planned price"), and founders log evidence rows with an optional
``observed_metric``. Nothing previously checked the two against each
other. This module closes that loop, purely:

* The latest *decisive* evidence row (PASS/FAIL) per assumption is judged.
* ``PASS`` at or above the method's canonical threshold → ``ON_TRACK``;
  ``FAIL`` below it → ``KILLED``.
* A PASS whose metric misses the bar is ``INCONSISTENT_PASS``; a FAIL whose
  metric clears it is ``INCONSISTENT_FAIL`` — both are surfaced rather than
  silently trusted.
* Rows without a metric, methods without a benchmark, inconclusive-only
  histories, and untouched assumptions get explicit verdicts too.

No I/O — the route layer resolves assumptions and evidence rows and calls
:func:`build_evidence_verdicts`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Canonical success bars as fractions, mirroring the conservative defaults
# in validation_experiment_planner.METHOD_SPECS success_threshold strings.
METHOD_THRESHOLDS: dict[str, float] = {
    "LANDING_PAGE_SMOKE_TEST": 0.03,
    "CONCIERGE_MVP": 0.60,
    "WILLINGNESS_TO_PAY_SURVEY": 0.30,
    "COMPETITIVE_DESK_RESEARCH": 0.50,
    "PROTOTYPE_USABILITY_TEST": 0.70,
    "PRE_ORDER_WAITLIST": 0.05,
    "PAID_ACQUISITION_TEST": 0.02,
    "USER_INTERVIEWS": 0.60,
}

_METHOD_LABELS: dict[str, str] = {
    "LANDING_PAGE_SMOKE_TEST": "Landing-page smoke test",
    "CONCIERGE_MVP": "Concierge MVP test",
    "WILLINGNESS_TO_PAY_SURVEY": "Willingness-to-pay survey",
    "COMPETITIVE_DESK_RESEARCH": "Competitive desk research",
    "PROTOTYPE_USABILITY_TEST": "Prototype usability test",
    "PRE_ORDER_WAITLIST": "Pre-order / waitlist test",
    "PAID_ACQUISITION_TEST": "Paid acquisition test",
    "USER_INTERVIEWS": "User interviews",
}

_VERDICT_ORDER = (
    "INCONSISTENT_PASS",
    "INCONSISTENT_FAIL",
    "KILLED",
    "ON_TRACK",
    "NO_METRIC",
    "UNBENCHMARKED_PASS",
    "UNBENCHMARKED_FAIL",
    "INCONCLUSIVE",
    "PENDING",
)


def _method_label(method: str | None) -> str:
    return _METHOD_LABELS.get(str(method or ""), "")


def _judge(
    result: str,
    method: str,
    observed_metric: float | None,
) -> tuple[str, float | None, float | None, str]:
    """Return (verdict, threshold, margin_pp, explanation) for one row."""
    label = _method_label(method)
    threshold = METHOD_THRESHOLDS.get(method)

    if threshold is None:
        if result == "PASS":
            return (
                "UNBENCHMARKED_PASS",
                None,
                None,
                f"Recorded PASS via {label or method}; no numeric bar exists "
                "for this method — founder judgment stands.",
            )
        return (
            "UNBENCHMARKED_FAIL",
            None,
            None,
            f"Recorded FAIL via {label or method}; no numeric bar exists "
            "for this method — founder judgment stands.",
        )

    if observed_metric is None:
        return (
            "NO_METRIC",
            threshold,
            None,
            f"No observed metric recorded, so the {label.lower()} bar of "
            f"{threshold:.0%} cannot be checked; founder recorded {result}.",
        )

    margin_pp = round((observed_metric - threshold) * 100.0, 4)
    if result == "PASS":
        if observed_metric >= threshold:
            return (
                "ON_TRACK",
                threshold,
                margin_pp,
                f"PASS with {observed_metric:.1%} against a {threshold:.0%} "
                f"{label.lower()} bar (+{margin_pp:.2f}pp).",
            )
        return (
            "INCONSISTENT_PASS",
            threshold,
            margin_pp,
            f"Recorded PASS but {observed_metric:.1%} sits below the "
            f"{threshold:.0%} {label.lower()} bar ({margin_pp:.2f}pp) — "
            "re-check the call.",
        )
    # FAIL rows
    if observed_metric < threshold:
        return (
            "KILLED",
            threshold,
            margin_pp,
            f"FAIL with {observed_metric:.1%} against a {threshold:.0%} "
            f"{label.lower()} bar ({margin_pp:.2f}pp).",
        )
    return (
        "INCONSISTENT_FAIL",
        threshold,
        margin_pp,
        f"Recorded FAIL but {observed_metric:.1%} clears the "
        f"{threshold:.0%} {label.lower()} bar (+{margin_pp:.2f}pp) — "
        "re-check the call.",
    )


def build_evidence_verdicts(
    *,
    project_id: int,
    assumptions: list[Any],
    evidence: list[Any],
) -> dict[str, Any]:
    """
    Judge every assumption's latest decisive evidence against its bar.

    ``assumptions`` are the project's visible ORM rows; ``evidence`` are the
    project's AssumptionEvidence rows in any order (they are grouped by
    assumption id here). Returns a dict matching ``EvidenceVerdictsOut``.
    """
    evidence_by_assumption: dict[int, list[tuple[int, Any]]] = {}
    for row in evidence:
        key = int(getattr(row, "assumption_id", 0) or 0)
        seq = (
            getattr(row, "id", 0) or 0,
            getattr(row, "created_at", None),
        )
        bucket = evidence_by_assumption.setdefault(key, [])
        bucket.append((seq, row))

    def _latest_decisive(rows: list[tuple[tuple, Any]]) -> Any | None:
        """Newest PASS/FAIL row by (id, created_at); None if only inconclusive."""
        ordered = sorted(rows, key=lambda pair: pair[0], reverse=True)
        for _, row in ordered:
            if str(getattr(row, "result", "")).upper() in ("PASS", "FAIL"):
                return row
        return None

    judged_rows: list[dict[str, Any]] = []
    counts = {
        "ON_TRACK": 0,
        "KILLED": 0,
        "INCONSISTENT_PASS": 0,
        "INCONSISTENT_FAIL": 0,
        "NO_METRIC": 0,
        "UNBENCHMARKED_PASS": 0,
        "UNBENCHMARKED_FAIL": 0,
        "INCONCLUSIVE": 0,
        "PENDING": 0,
    }

    for assumption in assumptions:
        assumption_id = int(getattr(assumption, "id", 0) or 0)
        history = evidence_by_assumption.get(assumption_id, [])
        latest = _latest_decisive(history)

        if not history:
            verdict = "PENDING"
            row_out = {
                "assumption_id": assumption_id,
                "assumption_text": getattr(assumption, "text", "") or "",
                "category": getattr(assumption, "category", None),
                "evidence_count": 0,
                "latest_result": None,
                "latest_method": None,
                "method_label": "",
                "threshold": None,
                "observed_metric": None,
                "margin_pp": None,
                "verdict": verdict,
                "explanation": "No experiments logged yet.",
            }
        elif latest is None:
            verdict = "INCONCLUSIVE"
            row_out = {
                "assumption_id": assumption_id,
                "assumption_text": getattr(assumption, "text", "") or "",
                "category": getattr(assumption, "category", None),
                "evidence_count": len(history),
                "latest_result": str(
                    getattr(history[-1][1], "result", "") or ""
                ).upper() or None,
                "latest_method": str(
                    getattr(history[-1][1], "method", "") or ""
                ) or None,
                "method_label": _method_label(
                    getattr(history[-1][1], "method", None)
                ),
                "threshold": None,
                "observed_metric": None,
                "margin_pp": None,
                "verdict": verdict,
                "explanation": (
                    "Only INCONCLUSIVE experiments so far — run a decisive "
                    "test before judging this claim."
                ),
            }
        else:
            result = str(getattr(latest, "result", "") or "").upper()
            method = str(getattr(latest, "method", "") or "")
            observed_metric = getattr(latest, "observed_metric", None)
            verdict, threshold, margin_pp, explanation = _judge(
                result, method, observed_metric
            )
            row_out = {
                "assumption_id": assumption_id,
                "assumption_text": getattr(assumption, "text", "") or "",
                "category": getattr(assumption, "category", None),
                "evidence_count": len(history),
                "latest_result": result,
                "latest_method": method,
                "method_label": _method_label(method),
                "threshold": threshold,
                "observed_metric": (
                    float(observed_metric)
                    if observed_metric is not None
                    else None
                ),
                "margin_pp": margin_pp,
                "verdict": verdict,
                "explanation": explanation,
            }

        counts[verdict] += 1
        judged_rows.append(row_out)

    attention_order = {v: i for i, v in enumerate(_VERDICT_ORDER)}
    judged_rows.sort(
        key=lambda r: (
            attention_order.get(str(r["verdict"]), len(_VERDICT_ORDER)),
            -(r["evidence_count"]),
            r["assumption_id"],
        )
    )

    total = len(judged_rows)
    on_track = counts["ON_TRACK"] + counts["UNBENCHMARKED_PASS"]
    killed = counts["KILLED"] + counts["UNBENCHMARKED_FAIL"]
    inconsistent = counts["INCONSISTENT_PASS"] + counts["INCONSISTENT_FAIL"]
    unjudged = total - on_track - killed - inconsistent

    if total == 0:
        next_action = "Import or create assumptions to start validating."
    elif inconsistent:
        next_action = (
            f"{inconsistent} record(s) contradict their own metric — "
            "re-check those calls first."
        )
    elif killed:
        next_action = (
            f"{killed} assumption(s) hit a kill bar — pivot or reframe "
            "before spending more."
        )
    elif on_track:
        next_action = (
            f"{on_track} assumption(s) are on track; keep testing the "
            f"{unjudged} still unjudged." if unjudged else
            f"All {on_track} judged assumption(s) are on track."
        )
    else:
        next_action = "Run the top planned experiments to start judging claims."

    return {
        "project_id": project_id,
        "total_assumptions": total,
        "judged_count": on_track + killed + inconsistent,
        "on_track_count": on_track,
        "killed_count": killed,
        "inconsistent_count": inconsistent,
        "unjudged_count": max(unjudged, 0),
        "rows": judged_rows,
        "next_action": next_action,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "evidence_verdicts_v1",
            "thresholds": dict(METHOD_THRESHOLDS),
            "judgment_rule": (
                "latest decisive evidence row per assumption; PASS at/above "
                "the method bar → ON_TRACK, FAIL below → KILLED, mismatches "
                "surfaced as INCONSISTENT_*"
            ),
        },
    }


__all__ = [
    "METHOD_THRESHOLDS",
    "build_evidence_verdicts",
]

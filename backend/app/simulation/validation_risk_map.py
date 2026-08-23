"""
Validation risk map: rank assumption categories by validation risk.

The per-assumption endpoints answer one question at a time — is this
claim killed, how trustworthy is its evidence. This module answers the
portfolio question: *which area of the business model has the weakest
validation story right now?* Assumptions are grouped by category
(pricing, demand, trust, …) and each group gets a transparent 0..1
risk score:

    (1.0 × killed + 0.6 × inconsistent + 0.5 × untested
     + 0.3 × low-quality tested + 0.1 × medium-quality tested)
        ÷ total assumptions in the category

"Killed" follows the verdicts scorecard's own rollup (KILLED plus
UNBENCHMARKED_FAIL), and quality labels come from the evidence-quality
grader, so this map never disagrees with the endpoints it summarises.
Categories are returned highest-risk first; the narrative names the
riskiest area.

Pure post-hoc composition of :func:`build_evidence_verdicts` and
:func:`build_evidence_quality` — no I/O, no LLM calls.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.simulation.evidence_quality import build_evidence_quality
from app.simulation.evidence_verdicts import build_evidence_verdicts

GENERAL_CATEGORY = "General"

# Transparent risk weights; surfaced verbatim in meta.risk_weights.
_RISK_WEIGHTS: dict[str, float] = {
    "killed": 1.0,
    "inconsistent": 0.6,
    "untested": 0.5,
    "low_quality_tested": 0.3,
    "medium_quality_tested": 0.1,
}

_KILLED_VERDICTS = frozenset({"KILLED", "UNBENCHMARKED_FAIL"})
_INCONSISTENT_VERDICTS = frozenset(
    {"INCONSISTENT_PASS", "INCONSISTENT_FAIL"}
)


def _category_of(assumption: Any) -> str:
    raw = getattr(assumption, "category", None)
    text = str(raw or "").strip()
    return text or GENERAL_CATEGORY


def _bucket() -> dict[str, Any]:
    return {
        "total": 0,
        "on_track": 0,
        "killed": 0,
        "inconsistent": 0,
        "unjudged": 0,
        "quality_rows": [],
    }


def build_validation_risk_map(
    *,
    project_id: int,
    assumptions: list[Any],
    evidence: list[Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Group every assumption by category and rank the groups by validation
    risk. Returns a dict matching ``ValidationRiskMapOut``.
    """
    now = now or datetime.now(UTC)

    verdicts = build_evidence_verdicts(
        project_id=project_id,
        assumptions=assumptions,
        evidence=evidence,
    )
    quality = build_evidence_quality(
        project_id=project_id,
        assumptions=assumptions,
        evidence=evidence,
        now=now,
    )
    verdict_by_id = {
        int(row["assumption_id"]): row for row in verdicts["rows"]
    }
    quality_by_id = {
        int(row["assumption_id"]): row for row in quality["rows"]
    }

    buckets: dict[str, dict[str, Any]] = {}
    for assumption in assumptions:
        category = _category_of(assumption)
        bucket = buckets.setdefault(category, _bucket())
        assumption_id = int(getattr(assumption, "id", 0) or 0)
        bucket["total"] += 1

        quality_row = quality_by_id.get(assumption_id)
        if quality_row is not None:
            bucket["quality_rows"].append(quality_row)

        verdict_row = verdict_by_id.get(assumption_id)
        if verdict_row is not None:
            verdict = str(verdict_row.get("verdict") or "")
            if verdict in _KILLED_VERDICTS:
                bucket["killed"] += 1
            elif verdict in _INCONSISTENT_VERDICTS:
                bucket["inconsistent"] += 1
            elif verdict in ("ON_TRACK", "UNBENCHMARKED_PASS"):
                bucket["on_track"] += 1
            else:
                bucket["unjudged"] += 1
        elif quality_row is not None:
            # Tested but the verdicts pass produced no judgement for it.
            bucket["unjudged"] += 1

    categories_out: list[dict[str, Any]] = []
    for category in sorted(buckets):
        bucket = buckets[category]
        total = bucket["total"]
        quality_rows = bucket["quality_rows"]
        tested = len(quality_rows)

        mean_quality = None
        weakest: dict[str, Any] | None = None
        low = medium = 0
        if quality_rows:
            qualities = [float(row["quality"]) for row in quality_rows]
            mean_quality = round(sum(qualities) / len(qualities), 4)
            low = sum(1 for q in qualities if q < 0.45)
            medium = sum(1 for q in qualities if 0.45 <= q < 0.70)
            weakest = min(quality_rows, key=lambda r: r["quality"])

        risk_score = round(
            (
                _RISK_WEIGHTS["killed"] * bucket["killed"]
                + _RISK_WEIGHTS["inconsistent"] * bucket["inconsistent"]
                + _RISK_WEIGHTS["untested"] * (total - tested)
                + _RISK_WEIGHTS["low_quality_tested"] * low
                + _RISK_WEIGHTS["medium_quality_tested"] * medium
            )
            / max(total, 1),
            4,
        )

        def _label(value: float | None) -> str | None:
            if value is None:
                return None
            if value >= 0.70:
                return "HIGH"
            if value >= 0.45:
                return "MEDIUM"
            return "LOW"

        categories_out.append(
            {
                "category": category,
                "total_assumptions": total,
                "tested_count": tested,
                "untested_count": total - tested,
                "on_track_count": bucket["on_track"],
                "killed_count": bucket["killed"],
                "inconsistent_count": bucket["inconsistent"],
                "unjudged_count": bucket["unjudged"],
                "mean_quality": mean_quality,
                "quality_label": _label(mean_quality),
                "weakest_assumption_id": (
                    int(weakest["assumption_id"]) if weakest else None
                ),
                "weakest_assumption_text": (
                    str(weakest.get("assumption_text") or "")
                    if weakest
                    else ""
                ),
                "weakest_quality": (
                    float(weakest["quality"]) if weakest else None
                ),
                "risk_score": risk_score,
            }
        )

    categories_out.sort(key=lambda c: (-c["risk_score"], c["category"]))

    total_assumptions = len(assumptions)
    rollup_killed = sum(c["killed_count"] for c in categories_out)
    rollup_inconsistent = sum(c["inconsistent_count"] for c in categories_out)
    rollup_on_track = sum(c["on_track_count"] for c in categories_out)
    tested_total = sum(c["tested_count"] for c in categories_out)
    untested_total = total_assumptions - tested_total

    riskiest = categories_out[0] if categories_out else None
    if riskiest is None:
        narrative = "No assumptions to map yet."
    else:
        narrative = (
            f"{riskiest['category']} carries the most validation risk: "
            f"{riskiest['killed_count']} killed, "
            f"{riskiest['inconsistent_count']} inconsistent, and "
            f"{riskiest['untested_count']} untested of "
            f"{riskiest['total_assumptions']} assumption(s)."
        )

    return {
        "project_id": project_id,
        "category_count": len(categories_out),
        "total_assumptions": total_assumptions,
        "tested_count": tested_total,
        "untested_count": max(untested_total, 0),
        "on_track_count": rollup_on_track,
        "killed_count": rollup_killed,
        "inconsistent_count": rollup_inconsistent,
        "riskiest_category": (
            riskiest["category"] if riskiest else None
        ),
        "categories": categories_out,
        "narrative": narrative,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "validation_risk_map_v1",
            "risk_weights": dict(_RISK_WEIGHTS),
            "sources": [
                "evidence_verdicts_v1",
                "evidence_quality_v1",
            ],
        },
    }


__all__ = [
    "build_validation_risk_map",
]

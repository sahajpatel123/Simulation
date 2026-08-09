"""
Pure investor-readiness digest for completed simulation results.

Answers the founder's "can I raise on these signals?" question by
consolidating six existing deterministic reads into one scorecard:

* **Market size** — TAM / SAM / SOM and projected annual revenue
  (``build_market_sizing``).
* **Unit economics** — blended LTV:CAC and payback
  (``build_unit_economics``).
* **Retention** — weighted day-30 / day-90 survival
  (``build_retention_churn``).
* **Defensibility** — weighted moat index
  (``build_competitive_moat``).
* **Launch readiness** — checklist readiness score
  (``build_launch_checklist``).
* **Data trust** — simulation quality trust score
  (``build_simulation_quality``).

Each pillar is scored 0..100 (``None`` when the underlying read has
insufficient data) and the available pillars are combined with fixed
weights into an overall investor score. Verdict bands:

* ``>= 80`` INVESTMENT_GRADE
* ``>= 60`` RAISABLE
* ``>= 40`` PRE_SEED
* otherwise NOT_INVESTABLE
* fewer than three scored pillars → INSUFFICIENT_DATA

The digest also emits the strongest pillars, the weakest pillars plus
critical findings, and a ranked list of top actions (weakest-pillar
action first, then recommendations from the readiness and quality
reads). No DB / I/O — verifiable without FastAPI or PostgreSQL. The
route layer supplies the six pillar payloads; all arithmetic is
deterministic. Pillar inputs are sanitised defensively: non-finite
values are treated as missing and negative / out-of-range numbers are
clamped to their natural domains (shares to 0..1, market counts to
non-negative) so malformed legacy payloads cannot distort the digest.
"""
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel

from app.schemas.investor_readiness import (
    InvestorPillar,
    InvestorReadinessOut,
)

# Fixed pillar weights — sum to 1.0. Economics and market carry the
# most weight because investors underwrite growth and gross-margin
# potential first; retention, moat, readiness and trust temper the
# headline.
PILLAR_WEIGHTS: dict[str, float] = {
    "market": 0.20,
    "economics": 0.25,
    "retention": 0.15,
    "moat": 0.20,
    "readiness": 0.10,
    "trust": 0.10,
}

PILLAR_LABELS: dict[str, str] = {
    "market": "Market size",
    "economics": "Unit economics",
    "retention": "Retention",
    "moat": "Defensibility",
    "readiness": "Launch readiness",
    "trust": "Data trust",
}

# How many scored pillars are required before an overall score exists.
MIN_AVAILABLE_PILLARS: int = 3

# Overall verdict bands (score is 0..100).
INVESTMENT_GRADE_MIN: int = 80
RAISABLE_MIN: int = 60
PRE_SEED_MIN: int = 40

VERDICT_INVESTMENT_GRADE: str = "INVESTMENT_GRADE"
VERDICT_RAISABLE: str = "RAISABLE"
VERDICT_PRE_SEED: str = "PRE_SEED"
VERDICT_NOT_INVESTABLE: str = "NOT_INVESTABLE"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VERDICT_LABELS: dict[str, str] = {
    VERDICT_INVESTMENT_GRADE: "Venture-grade signals",
    VERDICT_RAISABLE: "Investable at seed",
    VERDICT_PRE_SEED: "Pre-seed signals",
    VERDICT_NOT_INVESTABLE: "Not investable yet",
    VERDICT_INSUFFICIENT: "Insufficient data",
}

# Pillar verdict bands (score 0..100).
PILLAR_STRONG_MIN: int = 70
PILLAR_MODERATE_MIN: int = 45

PILLAR_VERDICT_STRONG: str = "STRONG"
PILLAR_VERDICT_MODERATE: str = "MODERATE"
PILLAR_VERDICT_WEAK: str = "WEAK"
PILLAR_VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

# A pillar at or above this score counts as a strength.
STRENGTH_MIN_SCORE: int = 70
# A pillar below this score counts as a risk.
RISK_MAX_SCORE: int = 45

MAX_STRENGTHS: int = 3
MAX_RISKS: int = 5
MAX_PILLAR_RISKS: int = 3
MAX_FINDING_RISKS: int = 2
MAX_TOP_ACTIONS: int = 5

# Action templates keyed by pillar — the weakest scored pillar's action
# is promoted to the top of the action list.
ACTION_TEMPLATES: dict[str, str] = {
    "market": (
        "Validate the obtainable market with real pre-orders or "
        "letters of intent before quoting TAM"
    ),
    "economics": (
        "Push blended LTV:CAC above 3x and payback under 18 months "
        "before raising"
    ),
    "retention": "Fix the day-30 retention drop before scaling acquisition",
    "moat": "Build evidence for the weakest defensibility lever",
    "readiness": "Close the top launch-checklist gap before shipping",
    "trust": (
        "Improve signal quality (add visible assumptions, rerun) "
        "before relying on projections"
    ),
}


def _safe_float(raw: Any, default: float | None = None) -> float | None:
    """Coerce a value to a finite ``float`` or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(raw: Any, default: int | None = None) -> int | None:
    """Coerce a value to an ``int`` or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_dict(value: Any) -> dict[str, Any] | None:
    """Normalise a pillar payload (Pydantic model or dict) to a dict."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return None


def _clamp_score(score: float) -> int:
    """Clamp a 0..100 float score to an int."""
    return max(0, min(100, int(round(score))))


def _clamp_unit(value: float) -> float:
    """Clamp a share/ratio into the 0..1 unit interval."""
    return max(0.0, min(1.0, value))


# Display caps for malformed extreme values. Scoring still uses the raw
# (non-negative) value; only the evidence string is bounded so a corrupt
# payload cannot print a 300-digit ratio or payback period.
ECONOMICS_RATIO_DISPLAY_CAP: float = 99.99
ECONOMICS_PAYBACK_DISPLAY_CAP: float = 999.0


def _pillar_verdict(score: int | None) -> str:
    if score is None:
        return PILLAR_VERDICT_INSUFFICIENT
    if score >= PILLAR_STRONG_MIN:
        return PILLAR_VERDICT_STRONG
    if score >= PILLAR_MODERATE_MIN:
        return PILLAR_VERDICT_MODERATE
    return PILLAR_VERDICT_WEAK


def _insufficient_pillar(key: str, summary: str = "") -> InvestorPillar:
    return InvestorPillar(
        key=key,
        label=PILLAR_LABELS.get(key, key),
        score=None,
        verdict=PILLAR_VERDICT_INSUFFICIENT,
        weight=PILLAR_WEIGHTS.get(key, 0.0),
        evidence=[],
        summary=summary,
    )


def _market_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar("market", "Market sizing read unavailable")
    tam = _safe_int(payload.get("tam_customers"))
    sam = _safe_int(payload.get("sam_customers"))
    som = _safe_int(payload.get("som_customers"))
    revenue = _safe_float(payload.get("annual_revenue"))
    if revenue is not None and revenue < 0.0:
        revenue = None
    if tam is not None:
        tam = max(0, tam)
    if sam is not None:
        sam = max(0, sam)
    if som is not None:
        som = max(0, som)

    if tam is None and som is None:
        return _insufficient_pillar("market", "Market sizing read unavailable")

    evidence = [
        f"TAM {tam or 0:,} · SAM {sam or 0:,} · SOM {som or 0:,} customers"
    ]
    if revenue is not None:
        evidence.append(f"Projected annual revenue {revenue:,.0f}")

    if revenue is not None and revenue > 0.0:
        if revenue >= 1_000_000:
            score = 100.0
            summary = "Projected revenue supports institutional capital"
        elif revenue >= 500_000:
            score = 85.0
            summary = "Projected revenue supports a strong seed case"
        elif revenue >= 250_000:
            score = 70.0
            summary = "Projected revenue supports a seed case"
        elif revenue >= 100_000:
            score = 55.0
            summary = "Projected revenue is modest but actionable"
        else:
            score = 40.0
            summary = "Projected revenue is small — validate before raising"
    elif som and som > 0:
        score = 20.0
        summary = "Reachable market exists but no revenue model (set AOV)"
    else:
        score = 10.0
        summary = "No obtainable market projected"

    if (som or 0) >= 1_000_000:
        score = min(100.0, score + 5.0)
    return InvestorPillar(
        key="market",
        label=PILLAR_LABELS["market"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["market"],
        evidence=evidence,
        summary=summary,
    )


def _economics_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar(
            "economics", "Unit-economics read unavailable"
        )
    if str(payload.get("verdict", "")).upper() == "INSUFFICIENT_DATA":
        return _insufficient_pillar(
            "economics", "Not enough unit-economics data"
        )
    ratio = _safe_float(payload.get("blended_ltv_cac_ratio"))
    if ratio is None:
        return _insufficient_pillar(
            "economics", "Not enough unit-economics data"
        )
    ratio = max(0.0, ratio)
    payback = _safe_float(payload.get("blended_payback_months"))
    if payback is not None and payback < 0.0:
        payback = None

    if ratio >= 3.0:
        score = 100.0
    elif ratio >= 1.5:
        score = 75.0
    elif ratio >= 1.0:
        score = 50.0
    elif ratio > 0.0:
        score = 30.0
    else:
        score = 15.0

    if ratio >= 1.0 and payback is not None:
        if payback <= 18.0:
            score = min(100.0, score + 5.0)
        elif payback > 36.0:
            score = max(0.0, score - 5.0)

    evidence = [f"Blended LTV:CAC {min(ratio, ECONOMICS_RATIO_DISPLAY_CAP):.2f}x"]
    if payback is not None:
        evidence.append(
            f"Blended payback {min(payback, ECONOMICS_PAYBACK_DISPLAY_CAP):.0f} months"
        )
    summary = (
        "Unit economics support a priced round"
        if ratio >= 3.0
        else "Unit economics need work before raising"
        if ratio < 1.5
        else "Unit economics are viable"
    )
    return InvestorPillar(
        key="economics",
        label=PILLAR_LABELS["economics"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["economics"],
        evidence=evidence,
        summary=summary,
    )


def _retention_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar(
            "retention", "Retention read unavailable"
        )
    if str(payload.get("verdict", "")).upper() == "INSUFFICIENT_DATA":
        return _insufficient_pillar(
            "retention", "Not enough retention data"
        )
    day30 = _safe_float(payload.get("weighted_day30_survival"))
    if day30 is None:
        return _insufficient_pillar(
            "retention", "Not enough retention data"
        )
    day30 = _clamp_unit(day30)
    day90 = _safe_float(payload.get("weighted_day90_survival"), 0.0)
    day90 = _clamp_unit(day90)

    if day30 >= 0.30:
        score = 100.0
    elif day30 >= 0.20:
        score = 80.0
    elif day30 >= 0.12:
        score = 60.0
    elif day30 >= 0.05:
        score = 40.0
    elif day30 > 0.0:
        score = 25.0
    else:
        score = 15.0

    if day90 >= 0.10:
        score = min(100.0, score + 5.0)

    evidence = [
        f"Day-30 survival {day30:.0%}",
        f"Day-90 survival {day90:.0%}",
    ]
    if payload.get("highest_churn_stage"):
        evidence.append(f"Biggest survival drop: {payload['highest_churn_stage']}")
    summary = (
        "Retention supports recurring revenue"
        if day30 >= 0.20
        else "Retention is a churn risk for investors"
        if day30 < 0.12
        else "Retention is acceptable but improvable"
    )
    return InvestorPillar(
        key="retention",
        label=PILLAR_LABELS["retention"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["retention"],
        evidence=evidence,
        summary=summary,
    )


def _moat_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar("moat", "Defensibility read unavailable")
    if str(payload.get("verdict", "")).upper() == "INSUFFICIENT_DATA":
        return _insufficient_pillar(
            "moat", "Not enough defensibility data"
        )
    index = _safe_float(payload.get("moat_index"))
    if index is None:
        return _insufficient_pillar(
            "moat", "Not enough defensibility data"
        )
    index = _clamp_unit(index)

    if index >= 0.60:
        score = 100.0
    elif index >= 0.50:
        score = 80.0
    elif index >= 0.40:
        score = 60.0
    elif index >= 0.25:
        score = 40.0
    elif index > 0.0:
        score = 25.0
    else:
        score = 15.0

    evidence = [f"Moat index {index:.2f}"]
    lever_label = payload.get("primary_weakest_lever_label") or ""
    if lever_label:
        evidence.append(f"Weakest lever: {lever_label}")
    summary = (
        "Defensibility is venture-grade"
        if index >= 0.60
        else "Defensibility is thin — competitors can copy quickly"
        if index < 0.40
        else "Defensibility is moderate"
    )
    return InvestorPillar(
        key="moat",
        label=PILLAR_LABELS["moat"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["moat"],
        evidence=evidence,
        summary=summary,
    )


def _readiness_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar(
            "readiness", "Launch-checklist read unavailable"
        )
    if str(payload.get("verdict", "")).upper() == "INSUFFICIENT_DATA":
        return _insufficient_pillar(
            "readiness", "Not enough launch-readiness data"
        )
    score_01 = _safe_float(payload.get("readiness_score"))
    if score_01 is None:
        return _insufficient_pillar(
            "readiness", "Not enough launch-readiness data"
        )
    score_01 = _clamp_unit(score_01)

    if score_01 >= 0.80:
        score = 100.0
    elif score_01 >= 0.65:
        score = 80.0
    elif score_01 >= 0.55:
        score = 60.0
    elif score_01 >= 0.40:
        score = 40.0
    elif score_01 > 0.0:
        score = 25.0
    else:
        score = 15.0

    evidence = [f"Launch readiness {score_01:.0%}"]
    verdict = payload.get("verdict") or ""
    if verdict:
        evidence.append(f"Checklist verdict {verdict}")
    summary = (
        "Launch signals are strong"
        if score_01 >= 0.80
        else "Launch signals need work before shipping"
        if score_01 < 0.55
        else "Launch signals are acceptable"
    )
    return InvestorPillar(
        key="readiness",
        label=PILLAR_LABELS["readiness"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["readiness"],
        evidence=evidence,
        summary=summary,
    )


def _trust_pillar(payload: dict[str, Any] | None) -> InvestorPillar:
    if not payload:
        return _insufficient_pillar("trust", "Quality-gate read unavailable")
    trust = _safe_float(payload.get("trust_score"))
    if trust is None:
        return _insufficient_pillar("trust", "Quality-gate read unavailable")
    trust = _clamp_unit(trust)

    if trust >= 0.80:
        score = 100.0
    elif trust >= 0.65:
        score = 80.0
    elif trust >= 0.50:
        score = 60.0
    elif trust >= 0.35:
        score = 40.0
    elif trust > 0.0:
        score = 25.0
    else:
        score = 15.0

    evidence = [f"Trust score {trust:.0%}"]
    verdict = payload.get("verdict") or ""
    if verdict:
        evidence.append(f"Quality verdict {verdict}")
    summary = (
        "Simulation numbers are trustworthy"
        if trust >= 0.65
        else "Simulation numbers need review before quoting"
        if trust < 0.50
        else "Simulation numbers are acceptable"
    )
    return InvestorPillar(
        key="trust",
        label=PILLAR_LABELS["trust"],
        score=_clamp_score(score),
        verdict=_pillar_verdict(_clamp_score(score)),
        weight=PILLAR_WEIGHTS["trust"],
        evidence=evidence,
        summary=summary,
    )


def _overall_verdict(score: int | None) -> tuple[str, str]:
    if score is None:
        return VERDICT_INSUFFICIENT, VERDICT_LABELS[VERDICT_INSUFFICIENT]
    if score >= INVESTMENT_GRADE_MIN:
        return VERDICT_INVESTMENT_GRADE, VERDICT_LABELS[VERDICT_INVESTMENT_GRADE]
    if score >= RAISABLE_MIN:
        return VERDICT_RAISABLE, VERDICT_LABELS[VERDICT_RAISABLE]
    if score >= PRE_SEED_MIN:
        return VERDICT_PRE_SEED, VERDICT_LABELS[VERDICT_PRE_SEED]
    return VERDICT_NOT_INVESTABLE, VERDICT_LABELS[VERDICT_NOT_INVESTABLE]


def _headline_conversion(results: dict[str, Any]) -> float | None:
    for key in ("population_weighted_conversion", "mean_conversion_rate", "conversion_rate"):
        value = _safe_float(results.get(key))
        if value is None or value < 0.0:
            continue
        return min(1.0, value)
    return None


def _finding_titles(
    findings: list[Any] | None, severities: frozenset[str]
) -> list[str]:
    out: list[str] = []
    for raw in findings or []:
        entry = _as_dict(raw)
        if not entry:
            continue
        severity = str(entry.get("severity") or "").upper()
        title = str(entry.get("title") or entry.get("finding") or "").strip()
        if severity in severities and title:
            out.append(title)
    return out


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def build_investor_readiness(
    results: Any,
    simulation_id: int,
    project_id: int,
    status: str = "COMPLETED",
    signal_quality: float | None = None,
    product_type: str = "saas",
    market: Any | None = None,
    economics: Any | None = None,
    retention: Any | None = None,
    moat: Any | None = None,
    readiness: Any | None = None,
    quality: Any | None = None,
    domain_findings: list[Any] | None = None,
) -> InvestorReadinessOut:
    """Compose the investor-readiness digest from completed pillar reads.

    Args:
        results: Simulation ``results_json`` (context only — headline
            conversion for ``meta``).
        simulation_id: Simulation primary key (echoed back).
        project_id: Owning project primary key (echoed back).
        status: Simulation status string.
        signal_quality: Persisted signal quality (0..1), if any.
        product_type: Detected product type for the run.
        market: ``MarketSizingOut`` payload or dict.
        economics: ``UnitEconomicsOut`` payload or dict.
        retention: ``RetentionChurnOut`` payload or dict.
        moat: ``CompetitiveMoatOut`` payload or dict.
        readiness: ``LaunchChecklistOut`` payload or dict.
        quality: ``SimulationQualityOut`` payload or dict.
        domain_findings: ``results_json["domain_findings"]`` rows, if any.
    """
    results_dict = _as_dict(results) or {}
    signal = _safe_float(signal_quality)
    if signal is not None and (signal < 0.0 or signal > 1.0):
        signal = None

    pillars = [
        _market_pillar(_as_dict(market)),
        _economics_pillar(_as_dict(economics)),
        _retention_pillar(_as_dict(retention)),
        _moat_pillar(_as_dict(moat)),
        _readiness_pillar(_as_dict(readiness)),
        _trust_pillar(_as_dict(quality)),
    ]

    scored = [p for p in pillars if p.score is not None]
    if len(scored) >= MIN_AVAILABLE_PILLARS:
        total_weight = sum(p.weight for p in scored)
        investor_score = _clamp_score(
            sum(p.score * p.weight for p in scored) / total_weight
            if total_weight > 0.0
            else 0.0
        )
    else:
        investor_score = None

    verdict, verdict_label = _overall_verdict(investor_score)

    strengths = [
        f"{p.label} ({p.score}/100)"
        for p in sorted(scored, key=lambda p: p.score or 0, reverse=True)
        if p.score is not None and p.score >= STRENGTH_MIN_SCORE
    ][:MAX_STRENGTHS]

    weak_pillars = [
        p for p in scored if p.score is not None and p.score < RISK_MAX_SCORE
    ]
    weak_pillars.sort(key=lambda p: p.score or 0)
    risks = [
        f"{p.label} ({p.score}/100)" for p in weak_pillars[:MAX_PILLAR_RISKS]
    ]
    critical_titles = _finding_titles(
        domain_findings, frozenset({"CRITICAL", "MAJOR"})
    )
    for title in critical_titles[:MAX_FINDING_RISKS]:
        risks.append(f"Finding: {title}")
    risks = _dedupe(risks)[:MAX_RISKS]

    weakest = scored[0] if scored else None
    for p in scored[1:]:
        if p.score is not None and (weakest is None or p.score < (weakest.score or 0)):
            weakest = p
    actions: list[str] = []
    if weakest is not None:
        template = ACTION_TEMPLATES.get(weakest.key, "")
        if template:
            actions.append(template)
    readiness_dict = _as_dict(readiness) or {}
    quality_dict = _as_dict(quality) or {}
    for raw in readiness_dict.get("recommendations", []) or []:
        if isinstance(raw, str):
            actions.append(raw)
    for raw in quality_dict.get("recommendations", []) or []:
        if isinstance(raw, str):
            actions.append(raw)
    actions = _dedupe(actions)[:MAX_TOP_ACTIONS]

    if investor_score is None:
        narrative = (
            "Investor readiness cannot be scored yet: "
            f"{len(scored)}/6 pillars have enough data. "
            "Rerun with more visible assumptions and real outcomes to "
            "unlock the digest."
        )
    else:
        strongest = strengths[0] if strengths else None
        weakest_label = weak_pillars[0].label if weak_pillars else None
        narrative = (
            f"Investor readiness {investor_score}/100 — {verdict_label}."
        )
        if strongest:
            narrative += f" Strongest pillar: {strongest.split(' (')[0]}."
        if weakest_label:
            narrative += f" Biggest risk: {weakest_label}."
        elif not strongest:
            narrative += " No pillar is strong yet."

    headline = _headline_conversion(results_dict)
    meta: dict[str, Any] = {
        "available_pillars": len(scored),
        "total_pillars": len(pillars),
        "weights": dict(PILLAR_WEIGHTS),
        "thresholds": {
            "investment_grade": INVESTMENT_GRADE_MIN,
            "raisable": RAISABLE_MIN,
            "pre_seed": PRE_SEED_MIN,
            "min_available_pillars": MIN_AVAILABLE_PILLARS,
        },
    }
    if headline is not None:
        meta["headline_conversion"] = round(headline, 4)

    return InvestorReadinessOut(
        simulation_id=simulation_id,
        project_id=project_id,
        status=status,
        product_type=str(product_type or "saas"),
        signal_quality=signal,
        investor_score=investor_score,
        verdict=verdict,  # type: ignore[arg-type]
        verdict_label=verdict_label,
        pillars=pillars,
        strengths=strengths,
        risks=risks,
        top_actions=actions,
        narrative=narrative,
        meta=meta,
    )


__all__ = ["build_investor_readiness"]

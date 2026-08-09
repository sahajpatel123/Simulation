"""Pure project-level go/no-go digest for launch decisions.

Answers the founder's final pre-launch question — "should I ship this?"
— by consolidating six existing deterministic reads into one launch
scorecard:

* **Launch readiness** — ``build_launch_checklist`` readiness score.
* **Risk posture** — ``build_premortem_digest`` severity breakdown.
* **Competitive position** — stored competitive-analysis position.
* **Data trust** — ``build_simulation_quality`` trust score.
* **Data freshness** — age of the latest simulation / assumptions /
  outcomes.
* **Assumption coverage** — ``build_coverage_gaps`` category coverage.

Each pillar is scored 0..100 (``None`` when the underlying read has
insufficient data) and the available pillars are combined with fixed
weights into an overall go/no-go score. Verdict bands:

* ``>= 75`` GO — but only when every evaluated launch gate passes
* ``>= 50`` CONDITIONAL_GO — launch with conditions
* otherwise NO_GO
* fewer than three scored pillars → INSUFFICIENT_DATA

Gates are binary pass/fail conditions (readiness strong enough, at most
one CRITICAL premortem failure mode, trust score >= 0.60, no critically
stale source, assumption coverage >= 6 of 9 standard categories). A
failed gate caps the verdict at CONDITIONAL_GO — a high score never
masks an unmet precondition.

The digest also emits strengths, risks, and a ranked list of top
actions (weakest-pillar action first, then gate-failure remediation).
No DB / I/O — verifiable without FastAPI or PostgreSQL. The route layer
supplies the six pillar payloads; all arithmetic is deterministic and
defensively sanitised: non-finite values are treated as missing and
out-of-range numbers are clamped so malformed legacy payloads cannot
distort the verdict.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.go_no_go import (
    GoNoGoGate,
    GoNoGoOut,
    GoNoGoPillar,
)

# Fixed pillar weights — sum to 1.0. Risk posture and readiness carry
# the most weight because launch is first an execution-risk decision;
# competitive position, data trust, freshness and coverage temper the
# headline.
PILLAR_WEIGHTS: dict[str, float] = {
    "readiness": 0.20,
    "premortem": 0.25,
    "competitive": 0.20,
    "trust": 0.15,
    "freshness": 0.10,
    "coverage": 0.10,
}

PILLAR_LABELS: dict[str, str] = {
    "readiness": "Launch readiness",
    "premortem": "Risk posture",
    "competitive": "Competitive position",
    "trust": "Data trust",
    "freshness": "Data freshness",
    "coverage": "Assumption coverage",
}

# How many scored pillars are required before an overall score exists.
MIN_AVAILABLE_PILLARS: int = 3

# Overall verdict bands (score is 0..100).
GO_MIN_SCORE: int = 75
CONDITIONAL_GO_MIN_SCORE: int = 50

VERDICT_GO: str = "GO"
VERDICT_CONDITIONAL_GO: str = "CONDITIONAL_GO"
VERDICT_NO_GO: str = "NO_GO"
VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

VERDICT_LABELS: dict[str, str] = {
    VERDICT_GO: "Signals support launch",
    VERDICT_CONDITIONAL_GO: "Launch with conditions",
    VERDICT_NO_GO: "Do not launch yet",
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
MAX_TOP_ACTIONS: int = 5

# Gate thresholds.
READINESS_GATE_SCORE: int = 80
RISK_GATE_MAX_CRITICAL: int = 1
TRUST_GATE_MIN_SCORE: float = 0.60
FRESHNESS_GATE_MAX_CRITICAL_SOURCES: int = 0
COVERAGE_GATE_MAX_MISSING: int = 3

# Staleness thresholds (days) for the freshness pillar — kept aligned
# with the per-project stale-check conventions.
SIM_STALE_DAYS: int = 14
ASSUMPTIONS_STALE_DAYS: int = 30
OUTCOMES_STALE_DAYS: int = 30

# A source at >= this multiple of its threshold is "critically stale".
CRITICAL_MULTIPLIER: float = 2.0

# Competitive-position base scores.
POSITION_SCORES: dict[str, float] = {
    "STRONG": 80.0,
    "MODERATE": 60.0,
    "WEAK": 35.0,
}

# High-threat competitors reduce the competitive score by this much
# each (capped at zero).
HIGH_THREAT_PENALTY: float = 8.0

# Premortem severity penalties (fraction of 100).
CRITICAL_PENALTY: float = 20.0
HIGH_PENALTY: float = 8.0
MEDIUM_PENALTY: float = 4.0
LOW_PENALTY: float = 1.0

# Assumption-coverage penalties.
MISSING_CATEGORY_PENALTY: float = 15.0
NO_HIGH_SENSITIVITY_PENALTY: float = 10.0

# Action templates keyed by pillar — the weakest scored pillar's action
# is promoted to the top of the action list.
ACTION_TEMPLATES: dict[str, str] = {
    "readiness": (
        "Close the top launch-checklist gap and re-run the "
        "simulation before shipping"
    ),
    "premortem": (
        "Address the top CRITICAL premortem failure modes before "
        "launch"
    ),
    "competitive": (
        "Build evidence against the highest-threat competitor "
        "before launch"
    ),
    "trust": (
        "Improve simulation trust (add visible assumptions, rerun) "
        "before relying on the numbers"
    ),
    "freshness": (
        "Refresh stale simulation / outcome data before making a "
        "launch decision"
    ),
    "coverage": (
        "Broaden assumption coverage to the missing standard "
        "categories before launch"
    ),
}

# Gate metadata: (id, label, remediation detail).
GATE_SPECS: dict[str, tuple[str, str, str]] = {
    "readiness_gate": (
        "Launch readiness is strong enough",
        "Launch-checklist readiness must reach 80/100",
    ),
    "risk_gate": (
        "Premortem risk is bounded",
        "At most one CRITICAL premortem failure mode",
    ),
    "trust_gate": (
        "Simulation data is trustworthy",
        "Simulation quality trust score must be >= 0.60",
    ),
    "freshness_gate": (
        "Launch data is fresh",
        "No critically stale simulation / assumption / outcome source",
    ),
    "coverage_gate": (
        "Assumption coverage is broad enough",
        "No more than 3 standard categories missing",
    ),
}


def _safe_float(raw: Any, default: float | None = None) -> float | None:
    """Coerce a value to a finite ``float`` or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(raw: Any, default: int = 0) -> int:
    """Coerce a value to a non-negative ``int`` or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


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


def _pillar_verdict(score: int | None) -> str:
    if score is None:
        return PILLAR_VERDICT_INSUFFICIENT
    if score >= PILLAR_STRONG_MIN:
        return PILLAR_VERDICT_STRONG
    if score >= PILLAR_MODERATE_MIN:
        return PILLAR_VERDICT_MODERATE
    return PILLAR_VERDICT_WEAK


def _insufficient_pillar(key: str, summary: str = "") -> GoNoGoPillar:
    return GoNoGoPillar(
        key=key,
        label=PILLAR_LABELS.get(key, key),
        score=None,
        verdict=PILLAR_VERDICT_INSUFFICIENT,
        weight=PILLAR_WEIGHTS.get(key, 0.0),
        evidence=[],
        summary=summary,
    )


def _readiness_pillar(payload: dict[str, Any] | None) -> GoNoGoPillar:
    if not payload:
        return _insufficient_pillar(
            "readiness", "Launch readiness read unavailable"
        )
    raw_score = _safe_float(payload.get("readiness_score"))
    if raw_score is None:
        return _insufficient_pillar(
            "readiness", "Launch readiness read unavailable"
        )
    score = _clamp_score(max(0.0, min(1.0, raw_score)) * 100.0)
    verdict_label = str(payload.get("verdict") or "UNKNOWN")
    evidence = [
        f"Launch-checklist readiness {score}/100 ({verdict_label})",
    ]
    recommendations = payload.get("recommendations") or []
    if (
        isinstance(recommendations, list)
        and recommendations
        and str(recommendations[0])
    ):
        evidence.append(f"Top recommendation: {recommendations[0]}")
    summary = (
        "Launch signals are ready"
        if verdict_label == "READY"
        else f"Launch readiness {score}/100"
    )
    return GoNoGoPillar(
        key="readiness",
        label=PILLAR_LABELS["readiness"],
        score=score,
        verdict=_pillar_verdict(score),
        weight=PILLAR_WEIGHTS["readiness"],
        evidence=evidence,
        summary=summary,
    )


def _premortem_pillar(payload: dict[str, Any] | None) -> GoNoGoPillar:
    if not payload:
        return _insufficient_pillar(
            "premortem", "Premortem read unavailable"
        )
    total = _safe_int(payload.get("premortem_count"))
    if total <= 0:
        return _insufficient_pillar(
            "premortem", "Premortem has not been run yet"
        )
    breakdown = payload.get("severity_breakdown") or {}
    if not isinstance(breakdown, dict):
        breakdown = {}
    critical = _safe_int(breakdown.get("CRITICAL"))
    high = _safe_int(breakdown.get("HIGH"))
    medium = _safe_int(breakdown.get("MEDIUM"))
    low = _safe_int(breakdown.get("LOW"))
    score = _clamp_score(
        100.0
        - critical * CRITICAL_PENALTY
        - high * HIGH_PENALTY
        - medium * MEDIUM_PENALTY
        - low * LOW_PENALTY
    )
    evidence = [
        f"{total} premortem failure mode(s) identified",
        (
            f"{critical} CRITICAL · {high} HIGH · "
            f"{medium} MEDIUM · {low} LOW"
        ),
    ]
    summary = (
        "Risk posture is clean"
        if critical == 0
        else f"{critical} CRITICAL failure mode(s)"
    )
    return GoNoGoPillar(
        key="premortem",
        label=PILLAR_LABELS["premortem"],
        score=score,
        verdict=_pillar_verdict(score),
        weight=PILLAR_WEIGHTS["premortem"],
        evidence=evidence,
        summary=summary,
    )


def _competitive_pillar(payload: dict[str, Any] | None) -> GoNoGoPillar:
    if not payload:
        return _insufficient_pillar(
            "competitive", "Competitive analysis unavailable"
        )
    position = str(
        payload.get("overall_competitive_position") or ""
    ).upper().strip()
    if position not in POSITION_SCORES:
        return _insufficient_pillar(
            "competitive", "Competitive analysis unavailable"
        )
    high_threat = _safe_int(payload.get("high_threat_count"))
    score = _clamp_score(
        POSITION_SCORES[position] - high_threat * HIGH_THREAT_PENALTY
    )
    evidence = [
        f"Overall competitive position: {position.title()}",
        f"{high_threat} high-threat competitor(s)",
    ]
    summary = f"Competitive position {position.title()}"
    return GoNoGoPillar(
        key="competitive",
        label=PILLAR_LABELS["competitive"],
        score=score,
        verdict=_pillar_verdict(score),
        weight=PILLAR_WEIGHTS["competitive"],
        evidence=evidence,
        summary=summary,
    )


def _trust_pillar(payload: dict[str, Any] | None) -> GoNoGoPillar:
    if not payload:
        return _insufficient_pillar("trust", "Simulation quality unavailable")
    raw_score = _safe_float(payload.get("trust_score"))
    if raw_score is None:
        return _insufficient_pillar("trust", "Simulation quality unavailable")
    score = _clamp_score(max(0.0, min(1.0, raw_score)) * 100.0)
    verdict_label = str(payload.get("verdict") or "UNKNOWN")
    evidence = [
        f"Simulation quality trust {score}/100 ({verdict_label})",
    ]
    summary = (
        "Simulation data is trustworthy"
        if score >= int(TRUST_GATE_MIN_SCORE * 100)
        else "Simulation data needs review"
    )
    return GoNoGoPillar(
        key="trust",
        label=PILLAR_LABELS["trust"],
        score=score,
        verdict=_pillar_verdict(score),
        weight=PILLAR_WEIGHTS["trust"],
        evidence=evidence,
        summary=summary,
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (or datetime) into an aware datetime."""
    if isinstance(raw, datetime):
        ts = raw
    elif isinstance(raw, str):
        try:
            ts = datetime.fromisoformat(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _freshness_pillar(
    payload: dict[str, Any] | None,
    now: datetime | None = None,
) -> tuple[GoNoGoPillar, dict[str, str]]:
    """Score data freshness; returns ``(pillar, source_statuses)``."""
    payload = payload or {}
    ref = _parse_timestamp(now) if now is not None else datetime.now(UTC)
    if ref is None:
        ref = datetime.now(UTC)

    sources: list[tuple[str, datetime | None, int]] = [
        (
            "simulation",
            _parse_timestamp(payload.get("latest_sim_completed_at")),
            SIM_STALE_DAYS,
        ),
        (
            "assumptions",
            _parse_timestamp(payload.get("latest_assumption_at")),
            ASSUMPTIONS_STALE_DAYS,
        ),
        (
            "outcomes",
            _parse_timestamp(payload.get("latest_outcome_at")),
            OUTCOMES_STALE_DAYS,
        ),
    ]

    evaluated: list[tuple[str, int, str]] = []
    source_statuses: dict[str, str] = {}
    for label, ts, threshold in sources:
        if ts is None:
            continue
        days = max(0, (ref - ts).days)
        if days >= int(threshold * CRITICAL_MULTIPLIER):
            status = "CRITICAL"
        elif days >= threshold:
            status = "WATCH"
        else:
            status = "OK"
        evaluated.append((label, days, status))
        source_statuses[label] = status

    if not evaluated:
        return (
            _insufficient_pillar(
                "freshness", "No simulation / outcome data to age"
            ),
            source_statuses,
        )

    raw = 100.0
    critical_count = 0
    for _label, _days, status in evaluated:
        if status == "CRITICAL":
            raw -= 25.0
            critical_count += 1
        elif status == "WATCH":
            raw -= 10.0
    score = _clamp_score(raw)
    evidence = [
        f"Latest {label} {days}d old"
        for label, days, _status in evaluated
    ]
    summary = (
        "All launch data is fresh"
        if critical_count == 0
        else f"{critical_count} critically stale source(s)"
    )
    return (
        GoNoGoPillar(
            key="freshness",
            label=PILLAR_LABELS["freshness"],
            score=score,
            verdict=_pillar_verdict(score),
            weight=PILLAR_WEIGHTS["freshness"],
            evidence=evidence,
            summary=summary,
        ),
        source_statuses,
    )


def _coverage_pillar(payload: dict[str, Any] | None) -> GoNoGoPillar:
    if not payload:
        return _insufficient_pillar(
            "coverage", "Assumption coverage unavailable"
        )
    total = _safe_int(payload.get("total_assumption_count"))
    if total <= 0:
        return _insufficient_pillar(
            "coverage", "No visible assumptions recorded yet"
        )
    missing = payload.get("missing_categories") or []
    if not isinstance(missing, list):
        missing = []
    sensitivity = payload.get("sensitivity_breakdown") or {}
    if not isinstance(sensitivity, dict):
        sensitivity = {}
    high_sensitivity = _safe_int(
        sensitivity.get("HIGH")
    ) + _safe_int(sensitivity.get("CRITICAL"))
    score = _clamp_score(
        100.0 - len(missing) * MISSING_CATEGORY_PENALTY
        - (NO_HIGH_SENSITIVITY_PENALTY if high_sensitivity == 0 else 0.0)
    )
    evidence = [
        f"{total} assumption(s) evaluated",
        f"{len(missing)} standard categor{'y' if len(missing) == 1 else 'ies'} missing",
    ]
    summary = (
        "Assumption coverage is broad"
        if len(missing) <= COVERAGE_GATE_MAX_MISSING
        else f"{len(missing)} standard categories missing"
    )
    return GoNoGoPillar(
        key="coverage",
        label=PILLAR_LABELS["coverage"],
        score=score,
        verdict=_pillar_verdict(score),
        weight=PILLAR_WEIGHTS["coverage"],
        evidence=evidence,
        summary=summary,
    )


def _build_gates(
    pillars: dict[str, GoNoGoPillar],
    premortem_payload: dict[str, Any] | None,
    coverage_payload: dict[str, Any] | None,
    freshness_statuses: dict[str, str],
) -> list[GoNoGoGate]:
    """Compose the five launch gates from evaluated pillar data."""
    gates: list[GoNoGoGate] = []

    readiness = pillars.get("readiness")
    if readiness is not None and readiness.score is not None:
        passed = readiness.score >= READINESS_GATE_SCORE
        detail = (
            f"Launch-checklist readiness {readiness.score}/100 "
            "(need >= 80)"
        )
    else:
        passed = None
        detail = "No completed simulation / launch-checklist read"
    gates.append(
        GoNoGoGate(
            id="readiness_gate",
            label=GATE_SPECS["readiness_gate"][0],
            evaluated=passed is not None,
            passed=passed,
            detail=detail,
        )
    )

    premortem = pillars.get("premortem")
    if premortem is not None and premortem.score is not None:
        critical = 0
        breakdown = (premortem_payload or {}).get(
            "severity_breakdown"
        ) or {}
        if isinstance(breakdown, dict):
            critical = _safe_int(breakdown.get("CRITICAL"))
        passed = critical <= RISK_GATE_MAX_CRITICAL
        detail = (
            f"{critical} CRITICAL premortem failure mode(s) "
            f"(max {RISK_GATE_MAX_CRITICAL})"
        )
    else:
        passed = None
        detail = "No premortem data to evaluate"
    gates.append(
        GoNoGoGate(
            id="risk_gate",
            label=GATE_SPECS["risk_gate"][0],
            evaluated=passed is not None,
            passed=passed,
            detail=detail,
        )
    )

    trust = pillars.get("trust")
    if trust is not None and trust.score is not None:
        passed = trust.score >= int(TRUST_GATE_MIN_SCORE * 100)
        detail = (
            f"Simulation quality trust {trust.score}/100 "
            "(need >= 60)"
        )
    else:
        passed = None
        detail = "No simulation quality data to evaluate"
    gates.append(
        GoNoGoGate(
            id="trust_gate",
            label=GATE_SPECS["trust_gate"][0],
            evaluated=passed is not None,
            passed=passed,
            detail=detail,
        )
    )

    if freshness_statuses:
        critical_sources = [
            label
            for label, status in freshness_statuses.items()
            if status == "CRITICAL"
        ]
        passed = len(critical_sources) <= FRESHNESS_GATE_MAX_CRITICAL_SOURCES
        detail = (
            "No critically stale source"
            if passed
            else f"Critically stale: {', '.join(sorted(critical_sources))}"
        )
    else:
        passed = None
        detail = "No simulation / outcome data to age"
    gates.append(
        GoNoGoGate(
            id="freshness_gate",
            label=GATE_SPECS["freshness_gate"][0],
            evaluated=passed is not None,
            passed=passed,
            detail=detail,
        )
    )

    coverage = pillars.get("coverage")
    if coverage is not None and coverage.score is not None:
        missing = (coverage_payload or {}).get("missing_categories") or []
        if not isinstance(missing, list):
            missing = []
        passed = len(missing) <= COVERAGE_GATE_MAX_MISSING
        detail = (
            f"{len(missing)} standard categor"
            f"{'y' if len(missing) == 1 else 'ies'} missing "
            f"(max {COVERAGE_GATE_MAX_MISSING})"
        )
    else:
        passed = None
        detail = "No assumption coverage data to evaluate"
    gates.append(
        GoNoGoGate(
            id="coverage_gate",
            label=GATE_SPECS["coverage_gate"][0],
            evaluated=passed is not None,
            passed=passed,
            detail=detail,
        )
    )

    return gates


def build_go_no_go(
    readiness: Any = None,
    premortem: Any = None,
    competitive: Any = None,
    trust: Any = None,
    freshness: Any = None,
    coverage: Any = None,
    project_id: int = 0,
    latest_simulation_id: int | None = None,
    now: datetime | None = None,
) -> GoNoGoOut:
    """Compose the project go/no-go digest.

    Args:
        readiness: output of :func:`build_launch_checklist` (or None).
        premortem: output of :func:`build_premortem_digest` (or None).
        competitive: stored competitive-analysis dict with
            ``overall_competitive_position`` and optional
            ``high_threat_count`` (or None).
        trust: output of :func:`build_simulation_quality` (or None).
        freshness: dict with ``latest_sim_completed_at`` /
            ``latest_assumption_at`` / ``latest_outcome_at`` ISO
            timestamps (or None).
        coverage: output of :func:`build_coverage_gaps` (or None).
        project_id: owning project primary key (echoed back).
        latest_simulation_id: latest completed simulation primary key
            (echoed back).
        now: optional reference time for the freshness pillar (for
            testability).

    Returns:
        Dict matching :class:`GoNoGoOut`.
    """
    readiness_payload = _as_dict(readiness)
    premortem_payload = _as_dict(premortem)
    competitive_payload = _as_dict(competitive)
    trust_payload = _as_dict(trust)
    coverage_payload = _as_dict(coverage)

    freshness_payload = (
        freshness.model_dump()
        if isinstance(freshness, BaseModel)
        else freshness if isinstance(freshness, dict) else None
    )
    freshness_pillar, freshness_statuses = _freshness_pillar(
        freshness_payload, now=now
    )

    pillars: list[GoNoGoPillar] = [
        _readiness_pillar(readiness_payload),
        _premortem_pillar(premortem_payload),
        _competitive_pillar(competitive_payload),
        _trust_pillar(trust_payload),
        freshness_pillar,
        _coverage_pillar(coverage_payload),
    ]
    pillars_by_key = {p.key: p for p in pillars}

    gates = _build_gates(
        pillars_by_key,
        premortem_payload,
        coverage_payload,
        freshness_statuses,
    )

    scored = [
        (p.key, p.score, p.weight)
        for p in pillars
        if p.score is not None
    ]
    if len(scored) < MIN_AVAILABLE_PILLARS:
        score: int | None = None
        verdict = VERDICT_INSUFFICIENT
    else:
        total_weight = sum(weight for _, _, weight in scored)
        if total_weight <= 0:
            score = None
            verdict = VERDICT_INSUFFICIENT
        else:
            score = _clamp_score(
                sum(s * w for _, s, w in scored) / total_weight
            )
            evaluated_gates = [g for g in gates if g.evaluated]
            all_gates_pass = bool(evaluated_gates) and all(
                g.passed for g in evaluated_gates
            )
            if score >= GO_MIN_SCORE and all_gates_pass:
                verdict = VERDICT_GO
            elif score >= CONDITIONAL_GO_MIN_SCORE:
                verdict = VERDICT_CONDITIONAL_GO
            else:
                verdict = VERDICT_NO_GO

    # ---- Strengths / risks ------------------------------------------
    strengths: list[str] = []
    risks: list[str] = []
    for pillar in pillars:
        if pillar.score is None:
            continue
        if pillar.score >= STRENGTH_MIN_SCORE:
            strengths.append(
                f"{pillar.label} is strong ({pillar.score}/100)"
            )
        elif pillar.score < RISK_MAX_SCORE:
            risks.append(
                f"{pillar.label} is weak ({pillar.score}/100) — "
                f"{pillar.summary}"
            )
    strengths = strengths[:MAX_STRENGTHS]
    risks = risks[:MAX_RISKS]

    # ---- Top actions ------------------------------------------------
    top_actions: list[str] = []
    weakest = None
    if scored:
        weakest = min(scored, key=lambda item: item[1])
        template = ACTION_TEMPLATES.get(weakest[0])
        if template:
            top_actions.append(template)

    for gate in gates:
        if gate.evaluated and gate.passed is False:
            top_actions.append(GATE_SPECS[gate.id][1])

    if premortem_payload:
        top_modes = premortem_payload.get("top_failure_modes") or []
        if (
            isinstance(top_modes, list)
            and top_modes
            and isinstance(top_modes[0], dict)
        ):
            title = top_modes[0].get("title")
            if title:
                top_actions.append(f"Address: {title}")

    seen: set[str] = set()
    deduped: list[str] = []
    for action in top_actions:
        if action and action not in seen:
            seen.add(action)
            deduped.append(action)
    top_actions = deduped[:MAX_TOP_ACTIONS]

    # ---- Narrative --------------------------------------------------
    if verdict == VERDICT_INSUFFICIENT:
        narrative = (
            f"Not enough launch signals yet "
            f"({len(scored)} of {len(pillars)} pillars available). "
            "Run a simulation, premortem and competitive analysis to "
            "get a go/no-go verdict."
        )
    else:
        failed_gates = [
            g for g in gates if g.evaluated and g.passed is False
        ]
        sentences = [
            f"Go/no-go score is {score}/100 — "
            f"{VERDICT_LABELS[verdict].lower()}."
        ]
        if failed_gates:
            sentences.append(
                f"{len(failed_gates)} launch gate(s) unmet "
                f"({', '.join(sorted(g.id.replace('_gate', '') for g in failed_gates))})."
            )
        else:
            sentences.append("All evaluated launch gates pass.")
        narrative = " ".join(sentences)

    evaluated_gates = [g for g in gates if g.evaluated]
    meta = {
        "total_pillars": len(pillars),
        "available_pillars": [key for key, _, _ in scored],
        "score_thresholds": {
            "go_min": GO_MIN_SCORE,
            "conditional_go_min": CONDITIONAL_GO_MIN_SCORE,
            "min_available_pillars": MIN_AVAILABLE_PILLARS,
        },
        "gate_summary": {
            "evaluated": len(evaluated_gates),
            "passed": sum(1 for g in evaluated_gates if g.passed),
            "failed": sum(
                1 for g in evaluated_gates if g.passed is False
            ),
        },
    }

    return GoNoGoOut(
        project_id=project_id,
        latest_simulation_id=latest_simulation_id,
        go_no_go_score=score,
        verdict=verdict,
        verdict_label=VERDICT_LABELS[verdict],
        pillars=pillars,
        gates=gates,
        strengths=strengths,
        risks=risks,
        top_actions=top_actions,
        narrative=narrative,
        meta=meta,
    )


__all__ = [
    "PILLAR_WEIGHTS",
    "PILLAR_LABELS",
    "MIN_AVAILABLE_PILLARS",
    "GO_MIN_SCORE",
    "CONDITIONAL_GO_MIN_SCORE",
    "VERDICT_GO",
    "VERDICT_CONDITIONAL_GO",
    "VERDICT_NO_GO",
    "VERDICT_INSUFFICIENT",
    "VERDICT_LABELS",
    "READINESS_GATE_SCORE",
    "RISK_GATE_MAX_CRITICAL",
    "TRUST_GATE_MIN_SCORE",
    "FRESHNESS_GATE_MAX_CRITICAL_SOURCES",
    "COVERAGE_GATE_MAX_MISSING",
    "build_go_no_go",
]

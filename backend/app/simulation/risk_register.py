"""Pure helpers for the per-project risk register digest.

Answers the founder question the individual digests only answer one at a
time: *"what are the biggest risks on this project right now, and what do I
do about them?"* The helper merges every deterministic risk source already
persisted for a project into one ranked, score-normalized register:

* **Premortem failure modes** (``project.premortem_json``) - each failure
  mode's ``impact`` x ``probability`` (with severity-derived fallbacks when
  one side is missing).
* **Assumption stress-test rows** (``project.stress_test_json``) - kill
  shots and sensitive assumptions, scored from ``kill_shot_prob`` and the
  projected conversion delta.
* **Competitive threats** (``project.competitive_json``) - competitors
  scored from threat level and the overall competitive position.
* **Simulation findings** (latest completed run's ``domain_findings``) -
  scored from severity and ``conversion_impact``.

Severities are normalized to CRITICAL / MAJOR / MINOR / INFO, every item
gets a 0..1 ``risk_score`` (probability x impact), and the register returns
the top risks (capped), severity/source breakdowns, an overall risk level,
and a founder-readable narrative.

Pure-Python - no SQL, no I/O - so the digest is verifiable without FastAPI
or PostgreSQL.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

# Unified severity buckets used across all four risk sources.
SEVERITY_CRITICAL: str = "CRITICAL"
SEVERITY_MAJOR: str = "MAJOR"
SEVERITY_MINOR: str = "MINOR"
SEVERITY_INFO: str = "INFO"

# Risk sources.
SOURCE_PREMORTEM: str = "PRE_MORTEM"
SOURCE_STRESS_TEST: str = "STRESS_TEST"
SOURCE_COMPETITIVE: str = "COMPETITIVE"
SOURCE_SIMULATION: str = "SIMULATION_FINDING"

# Overall risk levels.
RISK_LEVEL_LOW: str = "LOW"
RISK_LEVEL_MODERATE: str = "MODERATE"
RISK_LEVEL_HIGH: str = "HIGH"
RISK_LEVEL_SEVERE: str = "SEVERE"

# Cap on the ranked list so the founder-facing payload stays scannable;
# the counts and breakdowns still reflect every risk.
MAX_RISKS: int = 15

# Severity ranking for deterministic tie-breaking.
_SEVERITY_RANK: dict[str, int] = {
    SEVERITY_CRITICAL: 3,
    SEVERITY_MAJOR: 2,
    SEVERITY_MINOR: 1,
    SEVERITY_INFO: 0,
}

# Fallback probability / impact when a source omits one side.
_DEFAULT_PROBABILITY: dict[str, float] = {
    SEVERITY_CRITICAL: 0.80,
    SEVERITY_MAJOR: 0.55,
    SEVERITY_MINOR: 0.30,
    SEVERITY_INFO: 0.10,
}
_DEFAULT_IMPACT: dict[str, float] = {
    SEVERITY_CRITICAL: 0.90,
    SEVERITY_MAJOR: 0.60,
    SEVERITY_MINOR: 0.35,
    SEVERITY_INFO: 0.15,
}

# Competitive threat probability + severity mapping.
_THREAT_PROBABILITY: dict[str, float] = {
    "HIGH": 0.75,
    "MEDIUM": 0.50,
    "LOW": 0.25,
}
_THREAT_SEVERITY: dict[str, str] = {
    "HIGH": SEVERITY_MAJOR,
    "MEDIUM": SEVERITY_MINOR,
    "LOW": SEVERITY_INFO,
}

# Overall competitive position -> impact weight for competitor risks.
_COMPETITIVE_POSITION_IMPACT: dict[str, float] = {
    "HIGH_RISK": 0.80,
    "CHALLENGING": 0.75,
    "MODERATE": 0.60,
    "STRONG": 0.40,
    "DOMINANT": 0.25,
}

# Overall risk level thresholds on the top risk score.
_SEVERE_MIN_SCORE: float = 0.70
_HIGH_MIN_SCORE: float = 0.45
_MODERATE_MIN_SCORE: float = 0.25

# Architect-name substrings -> risk category for simulation findings.
_FINDING_CATEGORY_TERMS: tuple[tuple[str, str], ...] = (
    ("pricing", "PRICING"),
    ("trust", "TRUST"),
    ("distribution", "DISTRIBUTION"),
    ("channel", "DISTRIBUTION"),
    ("retention", "RETENTION"),
    ("onboarding", "ONBOARDING"),
    ("setup", "ONBOARDING"),
    ("regulatory", "REGULATORY"),
    ("compliance", "REGULATORY"),
    ("competitive", "COMPETITIVE"),
    ("virality", "VIRALITY"),
    ("support", "SUPPORT"),
    ("accessibility", "ACCESSIBILITY"),
    ("inclusion", "ACCESSIBILITY"),
    ("platform", "PLATFORM"),
    ("supply_chain", "SUPPLY_CHAIN"),
    ("sustainability", "SUSTAINABILITY"),
    ("cultural", "CULTURAL"),
    ("payment", "PAYMENT"),
    ("security", "SECURITY"),
    ("marketplace", "MARKETPLACE"),
    ("after_sales", "AFTER_SALES"),
    ("aftersales", "AFTER_SALES"),
    ("feature", "FEATURE"),
    ("integration", "INTEGRATION"),
    ("friction", "FRICTION"),
    ("purchase_decision", "PURCHASE"),
    ("behavioral", "BEHAVIORAL"),
    ("macroeconomic", "MACRO"),
    ("economy", "MACRO"),
    ("messaging", "MESSAGING"),
)


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(parsed):
        return None
    if parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _as_bool(value: Any) -> bool:
    """Coerce persisted booleans, including legacy string forms.

    JSONB payloads written by older exporters or external tools sometimes
    store ``kill_shot`` as ``"false"`` / ``"0"`` / ``"yes"`` instead of a
    real boolean.  ``bool("false")`` would wrongly read as True, so parse
    the common serialized forms explicitly and default unknown values to
    False (the conservative choice for a risk register).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return False


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalise_severity(raw: Any) -> str:
    """Map source severities (CRITICAL/SEVERE/HIGH/WARNING/MEDIUM/LOW...) to
    the unified CRITICAL / MAJOR / MINOR / INFO bucket."""
    value = str(raw or "").upper().strip()
    if value in {"CRITICAL", "SEVERE"}:
        return SEVERITY_CRITICAL
    if value in {"MAJOR", "HIGH", "WARNING"}:
        return SEVERITY_MAJOR
    if value in {"MINOR", "MODERATE", "MEDIUM"}:
        return SEVERITY_MINOR
    if value in {"INFO", "LOW"}:
        return SEVERITY_INFO
    return SEVERITY_MINOR


def _risk_score(
    *,
    severity: str,
    probability: float | None,
    impact: float | None,
) -> tuple[float, float, float]:
    """Resolve probability/impact fallbacks and the 0..1 risk score."""
    prob = (
        _clamp01(probability)
        if probability is not None
        else _DEFAULT_PROBABILITY[severity]
    )
    imp = (
        _clamp01(impact)
        if impact is not None
        else _DEFAULT_IMPACT[severity]
    )
    score = round(_clamp01(prob * imp), 4)
    return round(prob, 4), round(imp, 4), score


def _normalise_title(value: str) -> str:
    return " ".join(str(value).lower().split())


def _derive_category(terms: Any, fallback: str) -> str:
    """Map free text (architect names, premortem titles) to a risk
    category using the known domain terms, falling back when unknown."""
    text = str(terms or "").lower()
    for term, category in _FINDING_CATEGORY_TERMS:
        if term in text:
            return category
    return fallback


def _premortem_risks(data: Any) -> list[dict[str, Any]]:
    """Extract risks from ``project.premortem_json``."""
    payload = data if isinstance(data, dict) else {}
    raw_modes = (
        payload.get("failure_modes")
        or payload.get("modes")
        or payload.get("findings")
        or []
    )
    if not isinstance(raw_modes, list):
        raw_modes = []

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_modes):
        if not isinstance(raw, dict):
            continue
        severity = _normalise_severity(raw.get("severity"))
        probability = _safe_float(raw.get("probability"))
        impact = _safe_float(raw.get("impact"))
        prob, imp, score = _risk_score(
            severity=severity,
            probability=probability,
            impact=impact,
        )
        title = _safe_text(raw.get("title")) or (
            f"Premortem failure mode #{index + 1}"
        )
        items.append(
            {
                "id": f"premortem-{index}",
                "source": SOURCE_PREMORTEM,
                "category": _derive_category(title, "STRATEGIC"),
                "title": title,
                "description": (
                    _safe_text(raw.get("description"))
                    or _safe_text(raw.get("trigger_condition"))
                ),
                "severity": severity,
                "probability": prob,
                "impact": imp,
                "risk_score": score,
                "recommended_action": (
                    _safe_text(raw.get("intervention"))
                    or "Validate this failure mode with a real-world micro-test "
                    "before launch."
                ),
                "metric": None,
            }
        )
    return items


def _stress_test_risks(data: Any) -> list[dict[str, Any]]:
    """Extract risks from ``project.stress_test_json`` sensitivity rows."""
    payload = data if isinstance(data, dict) else {}
    raw_rows = payload.get("sensitivity_matrix") or []
    if not isinstance(raw_rows, list):
        raw_rows = []
    if not raw_rows:
        # Legacy payloads may only carry the pre-split kill-shot lists.
        for key in ("kill_shots", "partial_kill_shots"):
            legacy_rows = payload.get(key)
            if isinstance(legacy_rows, list):
                raw_rows.extend(legacy_rows)

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            continue
        kill_shot = _as_bool(raw.get("kill_shot"))
        delta = _safe_float(raw.get("delta"))
        partial = (
            not kill_shot
            and delta is not None
            and delta < -0.018
        )
        if kill_shot:
            severity = SEVERITY_CRITICAL
        elif partial:
            severity = SEVERITY_MAJOR
        else:
            severity = _normalise_severity(raw.get("sensitivity"))

        probability = _safe_float(raw.get("kill_shot_prob"))
        delta_pct = _safe_float(raw.get("delta_pct"))
        # Conversion-delta impact, floored by the severity's default so a
        # kill shot on a small absolute delta still ranks as critical.
        delta_impact = (
            _clamp01(abs(delta_pct) / 50.0)
            if delta_pct is not None
            else None
        )
        resolved_impact = (
            max(delta_impact, _DEFAULT_IMPACT[severity])
            if delta_impact is not None
            else None
        )
        prob, imp, score = _risk_score(
            severity=severity,
            probability=probability,
            impact=resolved_impact,
        )

        title = _safe_text(raw.get("assumption_text")) or (
            f"Stressed assumption #{index + 1}"
        )
        baseline = _safe_float(raw.get("baseline_conversion"))
        stressed = _safe_float(raw.get("stressed_conversion"))
        description_parts = [
            "Stressing this assumption shifts projected conversion"
        ]
        if delta_pct is not None:
            description_parts.append(f"by {abs(delta_pct):.1f}%")
        if baseline is not None and stressed is not None:
            description_parts.append(
                f"(baseline {baseline:.1%} -> stressed {stressed:.1%})"
            )
        description = " ".join(description_parts) + "."
        if kill_shot:
            description += " This assumption alone can collapse conversion."

        items.append(
            {
                "id": f"stress-{index}",
                "source": SOURCE_STRESS_TEST,
                "category": "SENSITIVE_ASSUMPTION",
                "title": title,
                "description": description,
                "severity": severity,
                "probability": prob,
                "impact": imp,
                "risk_score": score,
                "recommended_action": (
                    _safe_text(raw.get("recommendation"))
                    or "De-risk this assumption before launch."
                ),
                "metric": "conversion_delta_pct",
            }
        )
    return items


def _competitive_risks(data: Any) -> list[dict[str, Any]]:
    """Extract risks from ``project.competitive_json`` competitors."""
    payload = data if isinstance(data, dict) else {}
    raw_competitors = payload.get("competitors") or []
    if not isinstance(raw_competitors, list):
        raw_competitors = []

    position = str(
        payload.get("overall_competitive_position") or "MODERATE"
    ).upper().strip()
    position_impact = _COMPETITIVE_POSITION_IMPACT.get(position, 0.50)
    counter_moves = payload.get("gap_analysis") or {}
    if not isinstance(counter_moves, dict):
        counter_moves = {}
    raw_moves = counter_moves.get("recommended_counter_moves") or []
    first_move = (
        _safe_text(raw_moves[0])
        if isinstance(raw_moves, list) and raw_moves
        else ""
    )

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_competitors):
        if not isinstance(raw, dict):
            continue
        threat = str(raw.get("threat_level") or "LOW").upper().strip()
        if threat not in _THREAT_PROBABILITY:
            threat = "LOW"
        severity = _THREAT_SEVERITY[threat]
        prob, imp, score = _risk_score(
            severity=severity,
            probability=_THREAT_PROBABILITY[threat],
            impact=position_impact,
        )
        name = _safe_text(raw.get("name")) or f"Competitor #{index + 1}"
        description_parts = [
            _safe_text(raw.get("positioning"))
            or _safe_text(raw.get("target_segment"))
        ]
        weaknesses = raw.get("weaknesses")
        if isinstance(weaknesses, list) and weaknesses:
            description_parts.append(
                "Observed weaknesses: "
                + ", ".join(_safe_text(w) for w in weaknesses[:3])
            )
        description = " ".join(part for part in description_parts if part)

        items.append(
            {
                "id": f"competitive-{index}",
                "source": SOURCE_COMPETITIVE,
                "category": "COMPETITIVE",
                "title": f"{name} ({threat} threat)",
                "description": description,
                "severity": severity,
                "probability": prob,
                "impact": imp,
                "risk_score": score,
                "recommended_action": (
                    first_move
                    or "Differentiate on the gaps this competitor does not "
                    "cover and monitor its roadmap."
                ),
                "metric": "threat_level",
            }
        )
    return items


def _derive_finding_category(architect_name: Any) -> str:
    return _derive_category(architect_name, "PRODUCT")


def _finding_risks(findings: Any) -> list[dict[str, Any]]:
    """Extract risks from a simulation's ``domain_findings`` list."""
    raw_findings = findings if isinstance(findings, list) else []
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_findings):
        if not isinstance(raw, dict):
            continue
        severity = _normalise_severity(raw.get("severity"))
        conversion_impact = _safe_float(raw.get("conversion_impact"))
        impact = (
            _clamp01(abs(conversion_impact) * 5.0)
            if conversion_impact is not None
            else None
        )
        prob, imp, score = _risk_score(
            severity=severity,
            probability=None,
            impact=impact,
        )
        title = _safe_text(raw.get("finding")) or (
            f"Simulation finding #{index + 1}"
        )
        cluster = _safe_text(raw.get("cluster_name")) or _safe_text(
            raw.get("cluster_id")
        )
        actual = _safe_float(raw.get("actual_value"))
        benchmark = _safe_float(raw.get("healthy_benchmark"))
        description_parts: list[str] = []
        metric = _safe_text(raw.get("metric_affected"))
        if cluster:
            description_parts.append(f"Affects {cluster}")
        if metric and actual is not None and benchmark is not None:
            description_parts.append(
                f"{metric}: {actual:.3f} vs benchmark {benchmark:.3f}"
            )
        description = " | ".join(description_parts)

        items.append(
            {
                "id": f"finding-{index}",
                "source": SOURCE_SIMULATION,
                "category": _derive_finding_category(
                    raw.get("architect_name")
                ),
                "title": title,
                "description": description,
                "severity": severity,
                "probability": prob,
                "impact": imp,
                "risk_score": score,
                "recommended_action": (
                    _safe_text(raw.get("recommended_action"))
                    or "Review the affected metric and validate a fix."
                ),
                "metric": metric or None,
            }
        )
    return items


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicates (same source + normalized title).

    When two rows share a source and title but disagree on severity or
    scores, keep the higher-risk variant so the register never silently
    understates a risk.  Input order is preserved for ties.
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["source"], _normalise_title(item["title"]))
        current = seen.get(key)
        if current is None:
            seen[key] = item
            continue
        current_rank = (
            float(current["risk_score"]),
            _SEVERITY_RANK[current["severity"]],
        )
        item_rank = (
            float(item["risk_score"]),
            _SEVERITY_RANK[item["severity"]],
        )
        if item_rank > current_rank:
            seen[key] = item
    return list(seen.values())


def _sort_key(item: dict[str, Any]) -> tuple[float, int, str]:
    return (
        -float(item["risk_score"]),
        -_SEVERITY_RANK[item["severity"]],
        _normalise_title(item["title"]),
    )


def _overall_risk_level(top_score: float | None) -> str:
    if top_score is None:
        return RISK_LEVEL_LOW
    if top_score >= _SEVERE_MIN_SCORE:
        return RISK_LEVEL_SEVERE
    if top_score >= _HIGH_MIN_SCORE:
        return RISK_LEVEL_HIGH
    if top_score >= _MODERATE_MIN_SCORE:
        return RISK_LEVEL_MODERATE
    return RISK_LEVEL_LOW


def build_risk_register(
    *,
    project_id: int,
    premortem_data: Any = None,
    stress_test_data: Any = None,
    competitive_data: Any = None,
    findings: Any = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the consolidated, ranked risk register for a project.

    Args:
        project_id: owner-verified project id (route layer guarantees
            ownership before calling).
        premortem_data: ``project.premortem_json``.
        stress_test_data: ``project.stress_test_json``.
        competitive_data: ``project.competitive_json``.
        findings: latest completed simulation's ``domain_findings`` list.
        generated_at: ISO timestamp override (for testability).

    Returns:
        Dict matching the ``RiskRegisterOut`` schema: ranked ``risks``
        (capped), breakdowns, overall level, narrative and key signals.
    """
    if generated_at is None:
        generated_at = datetime.now(UTC).isoformat()

    all_items = _dedupe(
        _premortem_risks(premortem_data)
        + _stress_test_risks(stress_test_data)
        + _competitive_risks(competitive_data)
        + _finding_risks(findings)
    )
    ranked = sorted(all_items, key=_sort_key)
    total_risks = len(ranked)
    top_items = ranked[:MAX_RISKS]
    top_score = (
        round(float(ranked[0]["risk_score"]), 4) if ranked else None
    )
    overall_level = _overall_risk_level(top_score)

    # Stable canonical buckets so downstream charts never have to guess
    # which keys exist; zero counts are meaningful.
    severity_breakdown: dict[str, int] = {
        SEVERITY_CRITICAL: 0,
        SEVERITY_MAJOR: 0,
        SEVERITY_MINOR: 0,
        SEVERITY_INFO: 0,
    }
    source_breakdown: dict[str, int] = {
        SOURCE_PREMORTEM: 0,
        SOURCE_STRESS_TEST: 0,
        SOURCE_COMPETITIVE: 0,
        SOURCE_SIMULATION: 0,
    }
    for item in ranked:
        severity_breakdown[item["severity"]] += 1
        source_breakdown[item["source"]] += 1

    critical_count = severity_breakdown[SEVERITY_CRITICAL]
    active_source_count = sum(
        1 for count in source_breakdown.values() if count > 0
    )

    if not ranked:
        narrative = (
            "No risks identified yet - generate a premortem, stress test, "
            "competitive analysis, or run a simulation to populate the "
            "risk register."
        )
    else:
        sentences = [
            f"{total_risks} risk(s) identified across {active_source_count} "
            f"source(s); {critical_count} critical."
        ]
        top = ranked[0]
        sentences.append(
            f'Highest: "{top["title"]}" '
            f"(score {float(top['risk_score']):.2f})."
        )
        if top["recommended_action"]:
            sentences.append(
                "Start with: " + top["recommended_action"]
            )
        narrative = " ".join(sentences)

    key_signals: list[dict[str, Any]] = [
        {
            "label": "overall_risk_level",
            "value": overall_level,
            "severity": (
                "critical"
                if overall_level in {RISK_LEVEL_HIGH, RISK_LEVEL_SEVERE}
                else "watch"
                if overall_level == RISK_LEVEL_MODERATE
                else "ok"
            ),
            "display": f"Overall risk: {overall_level.lower()}",
        },
        {
            "label": "top_risk_score",
            "value": top_score,
            "severity": (
                "critical"
                if top_score is not None and top_score >= _HIGH_MIN_SCORE
                else "ok"
            ),
            "display": (
                f"Top risk score: {top_score:.2f}"
                if top_score is not None
                else "Top risk score: n/a"
            ),
        },
        {
            "label": "critical_risk_count",
            "value": critical_count,
            "severity": "critical" if critical_count else "ok",
            "display": f"{critical_count} critical risk(s)",
        },
        {
            "label": "total_risks",
            "value": total_risks,
            "severity": "watch" if total_risks else "ok",
            "display": f"{total_risks} risk(s) on the register",
        },
    ]

    return {
        "project_id": project_id,
        "generated_at": generated_at,
        "total_risks": total_risks,
        "top_risk_count": len(top_items),
        "overall_risk_level": overall_level,
        "top_risk_score": top_score,
        "severity_breakdown": severity_breakdown,
        "source_breakdown": source_breakdown,
        "risks": top_items,
        "narrative": narrative,
        "key_signals": key_signals,
    }


__all__ = [
    "MAX_RISKS",
    "RISK_LEVEL_HIGH",
    "RISK_LEVEL_LOW",
    "RISK_LEVEL_MODERATE",
    "RISK_LEVEL_SEVERE",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "SEVERITY_MAJOR",
    "SEVERITY_MINOR",
    "SOURCE_COMPETITIVE",
    "SOURCE_PREMORTEM",
    "SOURCE_SIMULATION",
    "SOURCE_STRESS_TEST",
    "build_risk_register",
]

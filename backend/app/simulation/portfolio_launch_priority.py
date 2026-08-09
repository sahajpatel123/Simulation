"""Pure helpers for the portfolio launch-priority digest.

Composes the per-project go/no-go scorecards (already computed by
the route layer with :func:`app.simulation.go_no_go.build_go_no_go`)
into one portfolio-level answer: **which project should the founder
launch first?**

Each project is bucketed by its canonical go/no-go verdict:

* ``LAUNCH_NOW`` — verdict ``GO`` (all evaluated launch gates pass).
* ``CONDITIONAL_LAUNCH`` — verdict ``CONDITIONAL_GO`` (launch with
  conditions).
* ``FIX_FIRST`` — verdict ``NO_GO`` (do not launch yet).
* ``PARK`` — verdict ``INSUFFICIENT_DATA`` (need more validation).

Projects are ranked by go/no-go score (descending), verdict priority
(GO > CONDITIONAL_GO > NO_GO > INSUFFICIENT_DATA), then freshness of
the latest completed simulation, then project id for a stable tie-
break. The digest emits a ``launch_sequence``, a single ``top_pick``
and a portfolio-wide ``next_focus`` — the weakest pillar across the
top ranked candidates — so the founder addresses the pattern that is
blocking most projects rather than only the single worst score.

The helper is pure-Python (no SQL, no I/O); every input is
defensively sanitised so malformed legacy payloads cannot crash the
digest or distort the ranking.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from app.simulation.go_no_go import (
    CONDITIONAL_GO_MIN_SCORE,
    GO_MIN_SCORE,
    PILLAR_LABELS,
    VERDICT_CONDITIONAL_GO,
    VERDICT_GO,
    VERDICT_INSUFFICIENT,
    VERDICT_NO_GO,
)

# Bucket names — echoed verbatim by the schema so the dashboard can
# hard-code the tile colours.
BUCKET_LAUNCH_NOW: str = "LAUNCH_NOW"
BUCKET_CONDITIONAL_LAUNCH: str = "CONDITIONAL_LAUNCH"
BUCKET_FIX_FIRST: str = "FIX_FIRST"
BUCKET_PARK: str = "PARK"

VALID_BUCKETS: frozenset[str] = frozenset({
    BUCKET_LAUNCH_NOW,
    BUCKET_CONDITIONAL_LAUNCH,
    BUCKET_FIX_FIRST,
    BUCKET_PARK,
})

# Portfolio-level verdict labels.
PORTFOLIO_VERDICT_READY: str = "READY_TO_LAUNCH"
PORTFOLIO_VERDICT_ALMOST_READY: str = "ALMOST_READY"
PORTFOLIO_VERDICT_NOT_READY: str = "NOT_READY"
PORTFOLIO_VERDICT_INSUFFICIENT: str = "INSUFFICIENT_DATA"

# Verdict priority for the tie-break (lower = launches sooner).
_VERDICT_PRIORITY: dict[str, int] = {
    VERDICT_GO: 0,
    VERDICT_CONDITIONAL_GO: 1,
    VERDICT_NO_GO: 2,
    VERDICT_INSUFFICIENT: 3,
}

# Caps — keep the dashboard tile readable and bound the payload.
MAX_LAUNCH_SEQUENCE: int = 25
MAX_BUCKET_ITEMS: int = 10
MAX_NEXT_FOCUS_CANDIDATES: int = 3
MAX_KEY_SIGNALS: int = 5

# Signal severity buckets — same convention as the other digests.
SIGNAL_OK: str = "ok"
SIGNAL_WATCH: str = "watch"
SIGNAL_CRITICAL: str = "critical"

# Focus templates keyed by pillar — reused wording from the
# go/no-go action templates so the dashboard's language stays
# consistent.
FOCUS_TEMPLATES: dict[str, str] = {
    "readiness": (
        "Raise launch-checklist readiness across the top candidates"
    ),
    "premortem": (
        "Resolve the recurring premortem failure modes before "
        "launching the top candidates"
    ),
    "competitive": (
        "Strengthen the competitive position of the top candidates"
    ),
    "trust": (
        "Improve simulation trust (add visible assumptions, rerun) "
        "for the top candidates"
    ),
    "freshness": (
        "Refresh stale simulation / outcome data for the top "
        "candidates"
    ),
    "coverage": (
        "Broaden assumption coverage for the top candidates"
    ),
}


def _safe_int(raw: Any, default: int = 0) -> int:
    """Coerce to a non-negative int or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, parsed)


def _safe_float(raw: Any, default: float | None = None) -> float | None:
    """Coerce to a finite float or return ``default``."""
    if raw is None or isinstance(raw, bool):
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _clamp_score(score: float | None) -> int | None:
    """Clamp a 0..100 float score to an int; ``None`` stays ``None``."""
    if score is None:
        return None
    return max(0, min(100, int(round(score))))


def _iso(value: Any) -> str | None:
    """ISO-format a datetime (or ISO string) defensively."""
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _epoch(value: Any) -> float:
    """Best-effort epoch seconds for a timestamp (0 when unknown)."""
    if value is None:
        return 0.0
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.timestamp()
    if isinstance(value, str) and value.strip():
        candidate = value.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    return 0.0


def _bucket_for(verdict: Any, score: int | None) -> str:
    """Map a go/no-go verdict (+ score) to a launch bucket."""
    if score is None or verdict == VERDICT_INSUFFICIENT:
        return BUCKET_PARK
    if verdict == VERDICT_GO:
        return BUCKET_LAUNCH_NOW
    if verdict == VERDICT_CONDITIONAL_GO:
        return BUCKET_CONDITIONAL_LAUNCH
    if verdict == VERDICT_NO_GO:
        return BUCKET_FIX_FIRST
    return BUCKET_PARK


def _reason_for(bucket: str, score: int | None) -> str:
    """Human-readable reason for a project's bucket."""
    if bucket == BUCKET_LAUNCH_NOW:
        return f"Signals support launch (go/no-go {score}/100)"
    if bucket == BUCKET_CONDITIONAL_LAUNCH:
        return (
            f"Launch with conditions (go/no-go {score}/100) — "
            "resolve the unmet gates first"
        )
    if bucket == BUCKET_FIX_FIRST:
        return (
            f"Do not launch yet (go/no-go {score}/100) — address "
            "the weakest pillar and unmet gates"
        )
    return (
        "Insufficient launch data — run a simulation, premortem and "
        "competitive analysis to get a go/no-go verdict"
    )


def _weakest_pillar(
    pillars: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Pick the scored pillar with the lowest score from a go/no-go
    payload's ``pillars`` list. ``None`` when nothing is scored."""
    best: dict[str, Any] | None = None
    for pillar in pillars or []:
        if not isinstance(pillar, dict):
            continue
        key = pillar.get("key")
        score = _safe_float(pillar.get("score"))
        if not isinstance(key, str) or not key or score is None:
            continue
        if best is None or score < _safe_float(best.get("score"), 101.0):
            best = {
                "key": key,
                "label": pillar.get("label") or PILLAR_LABELS.get(key, key),
                "score": _clamp_score(score),
            }
    return best


def _rank_key(item: dict[str, Any]) -> tuple:
    """Deterministic sort key: score desc, verdict priority asc,
    freshness desc, project id asc."""
    score = _safe_float(item.get("go_no_go_score"))
    verdict = str(item.get("verdict") or "")
    return (
        -1.0 if score is None else -score,
        _VERDICT_PRIORITY.get(verdict, 99),
        -_epoch(item.get("latest_simulation_at")),
        _safe_int(item.get("project_id")),
    )


def _portfolio_verdict(
    bucket_counts: dict[str, int],
) -> str:
    """Portfolio-level verdict from the bucket counts."""
    if bucket_counts.get(BUCKET_LAUNCH_NOW, 0) > 0:
        return PORTFOLIO_VERDICT_READY
    if bucket_counts.get(BUCKET_CONDITIONAL_LAUNCH, 0) > 0:
        return PORTFOLIO_VERDICT_ALMOST_READY
    if bucket_counts.get(BUCKET_FIX_FIRST, 0) > 0:
        return PORTFOLIO_VERDICT_NOT_READY
    return PORTFOLIO_VERDICT_INSUFFICIENT


def _next_focus(
    ranked: list[dict[str, Any]],
) -> str:
    """Find the weakest pillar across the top ranked candidates.

    Averages each pillar's score over the top
    :data:`MAX_NEXT_FOCUS_CANDIDATES` ranked projects (or all scored
    projects when fewer exist) and returns a focus string for the
    pillar with the lowest average. Returns an empty string when no
    pillar is scored anywhere.
    """
    candidates = ranked[:MAX_NEXT_FOCUS_CANDIDATES]
    if not candidates:
        return ""

    scores_by_key: dict[str, list[float]] = {}
    for item in candidates:
        for pillar in (item.get("pillars") or []):
            if not isinstance(pillar, dict):
                continue
            key = pillar.get("key")
            score = _safe_float(pillar.get("score"))
            if not isinstance(key, str) or not key or score is None:
                continue
            scores_by_key.setdefault(key, []).append(score)

    if not scores_by_key:
        return ""

    def _avg(key: str) -> float:
        values = scores_by_key[key]
        return sum(values) / len(values)

    weakest_key = min(
        scores_by_key,
        key=lambda key: (
            _avg(key),
            -len(scores_by_key[key]),
            key,
        ),
    )
    avg = _avg(weakest_key)
    count = len(scores_by_key[weakest_key])
    label = PILLAR_LABELS.get(weakest_key, weakest_key)
    template = FOCUS_TEMPLATES.get(
        weakest_key,
        f"Investigate the weakest pillar ({label})",
    )
    return (
        f"{template} — {label} averages {_clamp_score(avg)}/100 "
        f"across {count} top candidate(s)"
    )


def _key_signals(
    bucket_counts: dict[str, int],
    top_pick: dict[str, Any] | None,
    portfolio_verdict: str,
) -> list[dict[str, Any]]:
    """Structured dashboard signals for the digest."""
    signals: list[dict[str, Any]] = []

    launch_now = bucket_counts.get(BUCKET_LAUNCH_NOW, 0)
    signals.append({
        "label": "launch_now_count",
        "value": launch_now,
        "severity": SIGNAL_OK if launch_now > 0 else SIGNAL_WATCH,
        "display": (
            f"{launch_now} project(s) ready to launch now"
        ),
    })
    fix_first = bucket_counts.get(BUCKET_FIX_FIRST, 0)
    signals.append({
        "label": "fix_first_count",
        "value": fix_first,
        "severity": (
            SIGNAL_CRITICAL if fix_first >= 3
            else SIGNAL_WATCH if fix_first > 0 else SIGNAL_OK
        ),
        "display": (
            f"{fix_first} project(s) need fixes before launch"
        ),
    })
    parked = bucket_counts.get(BUCKET_PARK, 0)
    signals.append({
        "label": "park_count",
        "value": parked,
        "severity": (
            SIGNAL_WATCH if parked > 0 else SIGNAL_OK
        ),
        "display": (
            f"{parked} project(s) lack enough data to judge"
        ),
    })

    if top_pick is not None:
        score = top_pick.get("go_no_go_score")
        signals.append({
            "label": "top_pick_score",
            "value": score,
            "severity": (
                SIGNAL_OK if (score or 0) >= 75
                else SIGNAL_WATCH if (score or 0) >= 50
                else SIGNAL_CRITICAL
            ),
            "display": (
                f"Top pick: {top_pick.get('project_title') or 'project'} "
                f"({score}/100)"
            ),
        })

    signals.append({
        "label": "portfolio_verdict",
        "value": portfolio_verdict,
        "severity": (
            SIGNAL_OK if portfolio_verdict == PORTFOLIO_VERDICT_READY
            else SIGNAL_CRITICAL
            if portfolio_verdict == PORTFOLIO_VERDICT_NOT_READY
            else SIGNAL_WATCH
        ),
        "display": portfolio_verdict,
    })
    return signals[:MAX_KEY_SIGNALS]


def build_portfolio_launch_priority(
    project_payloads: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose the portfolio launch-priority digest.

    Args:
        project_payloads: list of per-project dicts. Each entry must
            expose ``project_id``, ``project_title``,
            ``go_no_go`` (a :class:`GoNoGoOut` dict — from
            ``build_go_no_go(...).model_dump()``), plus optional
            ``latest_simulation_at`` (datetime / ISO string) and
            ``has_outcomes`` (bool). Malformed entries are skipped.
        now: optional reference time for ``meta.generated_at`` (for
            testability). Defaults to ``datetime.now(UTC)``.

    Returns:
        Dict matching :class:`PortfolioLaunchPriorityOut`:

        * ``project_count`` — projects supplied.
        * ``evaluated_count`` — projects with a usable scorecard.
        * ``portfolio_verdict`` — READY_TO_LAUNCH / ALMOST_READY /
          NOT_READY / INSUFFICIENT_DATA.
        * ``top_pick`` — highest-ranked project (or ``None``).
        * ``buckets`` — per-bucket ranked item lists (all four keys
          always present, capped).
        * ``launch_sequence`` — ranked project ids (capped).
        * ``next_focus`` — weakest pillar across the top candidates.
        * ``narrative`` / ``key_signals`` / ``meta``.
    """
    payloads = [
        p for p in (project_payloads or []) if isinstance(p, dict)
    ]
    project_count = len(payloads)

    items: list[dict[str, Any]] = []
    for raw in payloads:
        go_no_go = raw.get("go_no_go")
        if not isinstance(go_no_go, dict):
            continue
        score = _safe_float(go_no_go.get("go_no_go_score"))
        clamped_score = _clamp_score(score)
        verdict = str(go_no_go.get("verdict") or VERDICT_INSUFFICIENT)
        bucket = _bucket_for(verdict, clamped_score)
        pillars = go_no_go.get("pillars")
        top_actions = go_no_go.get("top_actions") or []
        top_action = (
            str(top_actions[0])
            if isinstance(top_actions, list) and top_actions
            else ""
        )
        items.append({
            "project_id": _safe_int(raw.get("project_id")),
            "project_title": str(raw.get("project_title") or ""),
            "go_no_go_score": clamped_score,
            "verdict": verdict,
            "verdict_label": str(
                go_no_go.get("verdict_label") or ""
            ),
            "latest_simulation_id": (
                go_no_go.get("latest_simulation_id")
            ),
            "latest_simulation_at": _iso(
                raw.get("latest_simulation_at")
            ),
            "has_outcomes": bool(raw.get("has_outcomes")),
            "top_action": top_action,
            "reason": _reason_for(bucket, clamped_score),
            "weakest_pillar": _weakest_pillar(pillars),
            "pillars": pillars if isinstance(pillars, list) else [],
            "bucket": bucket,
        })

    # Drop zero-id rows (defensive — a malformed payload with no
    # project id would otherwise rank as a phantom project).
    items = [item for item in items if item["project_id"] > 0]
    ranked = sorted(items, key=_rank_key)

    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    # Strip the internal ``pillars`` working key before exposing the
    # items to the schema (the public item carries only
    # ``weakest_pillar``).
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key != "pillars"
        }

    public_items = [_public(item) for item in ranked]

    buckets: dict[str, list[dict[str, Any]]] = {
        bucket: [] for bucket in VALID_BUCKETS
    }
    bucket_counts: dict[str, int] = {
        bucket: 0 for bucket in VALID_BUCKETS
    }
    for item in public_items:
        bucket = item["bucket"]
        if len(buckets[bucket]) < MAX_BUCKET_ITEMS:
            buckets[bucket].append(item)
        bucket_counts[bucket] += 1

    top_pick = public_items[0] if public_items else None
    portfolio_verdict = _portfolio_verdict(bucket_counts)
    next_focus = _next_focus(ranked)

    launch_sequence = [
        item["project_id"] for item in ranked[:MAX_LAUNCH_SEQUENCE]
    ]

    if not ranked:
        narrative = (
            "No projects with a usable launch scorecard yet — run "
            "simulations, premortems and competitive analyses to "
            "unlock portfolio launch prioritisation."
        )
    else:
        sentences = [
            f"{len(ranked)} project(s) evaluated: "
            f"{bucket_counts[BUCKET_LAUNCH_NOW]} ready to launch, "
            f"{bucket_counts[BUCKET_CONDITIONAL_LAUNCH]} conditional, "
            f"{bucket_counts[BUCKET_FIX_FIRST]} need fixes, "
            f"{bucket_counts[BUCKET_PARK]} need more data."
        ]
        if top_pick is not None:
            score_text = (
                f"{top_pick['go_no_go_score']}/100"
                if top_pick["go_no_go_score"] is not None
                else "no score yet"
            )
            sentences.append(
                f"Top pick: {top_pick['project_title'] or 'project'} "
                f"({score_text}, "
                f"{top_pick['verdict_label'] or top_pick['verdict']})."
            )
        if next_focus:
            sentences.append(f"Portfolio focus: {next_focus}.")
        narrative = " ".join(sentences)

    reference = now if isinstance(now, datetime) else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)

    meta = {
        "generated_at": reference.astimezone(UTC).isoformat(),
        "evaluated_projects": len(ranked),
        "bucket_thresholds": {
            "go_requires_all_gates_passing": True,
            "conditional_go_min_score": CONDITIONAL_GO_MIN_SCORE,
            "go_min_score": GO_MIN_SCORE,
        },
        "caps": {
            "max_launch_sequence": MAX_LAUNCH_SEQUENCE,
            "max_bucket_items": MAX_BUCKET_ITEMS,
        },
    }

    return {
        "project_count": project_count,
        "evaluated_count": len(ranked),
        "portfolio_verdict": portfolio_verdict,
        "top_pick": top_pick,
        "buckets": buckets,
        "launch_sequence": launch_sequence,
        "next_focus": next_focus,
        "narrative": narrative,
        "key_signals": _key_signals(
            bucket_counts, top_pick, portfolio_verdict
        ),
        "meta": meta,
    }


__all__ = [
    "BUCKET_CONDITIONAL_LAUNCH",
    "BUCKET_FIX_FIRST",
    "BUCKET_LAUNCH_NOW",
    "BUCKET_PARK",
    "PORTFOLIO_VERDICT_ALMOST_READY",
    "PORTFOLIO_VERDICT_INSUFFICIENT",
    "PORTFOLIO_VERDICT_NOT_READY",
    "PORTFOLIO_VERDICT_READY",
    "build_portfolio_launch_priority",
]

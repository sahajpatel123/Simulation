"""
Assumption recovery planner: turn kill verdicts into concrete next plays.

The evidence-verdicts scorecard answers *which* assumptions died or
contradict their own records; this module answers the founder's next
question — *how do I get the idea back on track?* For every KILLED or
INCONSISTENT_* assumption it proposes ordered, deterministic recovery
plays: a reframed hypothesis plus a concrete re-test drawn from the same
``METHOD_SPECS`` table the experiment planner uses (method label, cost
tier, duration, sample target, success bar).

Plays are selected by *theme* — pricing, demand, trust, competition,
usability, retention, or general — inferred from the assumption's
category and text. Inconsistent records get an audit play prepended: the
cheapest recovery is verifying the bookkeeping before spending on new
experiments.

No I/O — the route layer resolves assumptions and evidence rows and calls
:func:`build_recovery_plan`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.recovery_plan import (
    RecoveryAction,
    RecoveryRow,
)
from app.simulation.evidence_verdicts import build_evidence_verdicts
from app.simulation.validation_experiment_planner import METHOD_SPECS

# Keyword themes used to pick a playbook. Matched against the lowercased
# category and assumption text together.
_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "pricing": (
        "pric",
        "cost",
        "fee",
        "pay",
        "wtp",
        "afford",
        "monetiz",
        "subscription",
        "premium",
    ),
    "demand": (
        "demand",
        "need",
        "sign up",
        "signup",
        "waitlist",
        "interest",
        "adopt",
        "landing",
        "convert",
    ),
    "trust": ("trust", "credib", "review", "brand", "secur", "privacy"),
    "competition": (
        "compet",
        "incumbent",
        "alternative",
        "switch",
        "rival",
    ),
    "usability": (
        "usab",
        "ux",
        "ui ",
        "onboard",
        "friction",
        "confus",
        "ease",
        "prototype",
    ),
    "retention": (
        "retention",
        "churn",
        "loyal",
        "stick",
        "return",
        "engag",
    ),
}

# Ordered (title, rationale, method) plays per theme. Method ids must be
# present in METHOD_SPECS; every field shown to the founder comes from
# there so the recovery plan never drifts from the experiment planner.
_THEME_PLAYBOOKS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "pricing": (
        (
            "Re-test willingness at a lower anchor price",
            "A pricing kill often means the price point failed, not the "
            "value — test the same promise at a materially lower anchor.",
            "WILLINGNESS_TO_PAY_SURVEY",
        ),
        (
            "Test freemium or trial-first monetization",
            "If outright payment fails, a free tier with paid upgrades can "
            "still capture demand while lowering the adoption bar.",
            "LANDING_PAGE_SMOKE_TEST",
        ),
        (
            "Re-target a less price-sensitive segment",
            "The claim may hold for a wealthier or more motivated audience "
            "— interview people who already pay for alternatives.",
            "USER_INTERVIEWS",
        ),
    ),
    "demand": (
        (
            "Sharpen positioning and re-run the smoke test",
            "Weak signup rates usually indict the message before the "
            "market — lead with the sharpest pain and a single CTA.",
            "LANDING_PAGE_SMOKE_TEST",
        ),
        (
            "Run problem interviews before building further",
            "Confirm the problem is urgent and frequent for real people "
            "before spending another rupee on acquisition.",
            "USER_INTERVIEWS",
        ),
        (
            "Deliver the value manually as a concierge pilot",
            "A concierge pilot tests whether people use the outcome, not "
            "just click the promise.",
            "CONCIERGE_MVP",
        ),
    ),
    "trust": (
        (
            "Add proof signals and re-test conversion",
            "Reviews, testimonials, and guarantees attack trust objections "
            "directly — measure the lift on the same funnel.",
            "LANDING_PAGE_SMOKE_TEST",
        ),
        (
            "Interview doubters about their trust blockers",
            "Ask what evidence would change their mind — refunds, security "
            "badges, known backers, local presence.",
            "USER_INTERVIEWS",
        ),
    ),
    "competition": (
        (
            "Map incumbent switching costs precisely",
            "Document what users must give up to switch — data, workflows, "
            "contracts — and where your wedge undercuts it.",
            "COMPETITIVE_DESK_RESEARCH",
        ),
        (
            "Interview recent switchers",
            "People who just left an incumbent reveal which switching "
            "friction actually breaks.",
            "USER_INTERVIEWS",
        ),
    ),
    "usability": (
        (
            "Re-test a simplified core flow",
            "Strip the flow to the single job-to-be-done and measure task "
            "completion on the leaner prototype.",
            "PROTOTYPE_USABILITY_TEST",
        ),
        (
            "Guide first sessions as a concierge",
            "Hand-holding through first use separates confusion from lack "
            "of motivation.",
            "CONCIERGE_MVP",
        ),
    ),
    "retention": (
        (
            "Pilot weekly touchpoints with a small cohort",
            "Retention failures are usually habit-formation failures — "
            "test reminders, streaks, or scheduled value delivery.",
            "CONCIERGE_MVP",
        ),
        (
            "Interview churned users about their last session",
            "Churn reasons cluster into a few fixable moments; find yours "
            "before rebuilding features.",
            "USER_INTERVIEWS",
        ),
    ),
    "general": (
        (
            "Run open-ended problem interviews",
            "When the failure mode is unclear, talk to target users before "
            "designing another experiment.",
            "USER_INTERVIEWS",
        ),
        (
            "Re-run a sharper landing-page smoke test",
            "A focused page with one message and one CTA is the cheapest "
            "clean signal available.",
            "LANDING_PAGE_SMOKE_TEST",
        ),
    ),
}

_TRIGGER_RANK = {"KILLED": 0, "INCONSISTENT_PASS": 1, "INCONSISTENT_FAIL": 1}


def _classify_theme(category: str | None, assumption_text: str) -> str:
    """Infer the recovery theme from category and text keywords."""
    haystack = f"{category or ''} {assumption_text}".lower()
    best_theme, best_hits = "general", 0
    for theme, keywords in _THEME_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits > best_hits:
            best_theme, best_hits = theme, hits
    return best_theme


def _action_from_spec(
    order: int,
    title: str,
    rationale: str,
    method: str,
) -> RecoveryAction:
    """Render one play using the canonical METHOD_SPECS entry."""
    spec = METHOD_SPECS.get(method, {})
    return RecoveryAction(
        order=order,
        title=title,
        rationale=rationale,
        method=method,  # type: ignore[arg-type]
        method_label=str(spec.get("label", method.replace("_", " ").title())),
        cost_tier=str(spec.get("cost_tier", "FREE")),  # type: ignore[arg-type]
        estimated_duration_days=int(spec.get("estimated_duration_days", 7)),
        sample_target=str(spec.get("sample_target", "")),
        success_metric=str(spec.get("success_metric", "")),
        success_threshold=str(spec.get("success_threshold", "")),
    )


def _audit_action(
    row: dict[str, Any],
) -> RecoveryAction | None:
    """Prepended play for inconsistent records: check the books first."""
    observed = row.get("observed_metric")
    threshold = row.get("threshold")
    verdict = row.get("trigger") or row.get("verdict") or ""
    if verdict == "INCONSISTENT_PASS":
        rationale = (
            "The record says PASS but the metric sits below the bar — "
            "verify the call and re-log the result before spending on new "
            "experiments."
        )
    elif verdict == "INCONSISTENT_FAIL":
        rationale = (
            "The record says FAIL but the metric clears the bar — verify "
            "the call and re-log the result before spending on new "
            "experiments."
        )
    else:
        return None
    if observed is not None and threshold is not None:
        rationale += (
            f" Recorded {observed:.1%} against a {threshold:.0%} bar."
        )
    method = str(row.get("latest_method") or "") or "USER_INTERVIEWS"
    spec = METHOD_SPECS.get(method, {})
    return RecoveryAction(
        order=1,
        title="Audit the recorded result against its metric",
        rationale=rationale,
        method=method,  # type: ignore[arg-type]
        method_label=str(spec.get("label", method)),
        cost_tier="FREE",
        estimated_duration_days=1,
        sample_target=str(spec.get("sample_target", "")),
        success_metric=str(spec.get("success_metric", "")),
        success_threshold=str(spec.get("success_threshold", "")),
    )


def _cheapest_action(row: RecoveryRow) -> RecoveryAction | None:
    """Lowest cost tier, then shortest duration, then first listed."""
    if not row.actions:
        return None
    cost_rank = {"FREE": 0, "LOW": 1, "MEDIUM": 2}
    return min(
        row.actions,
        key=lambda a: (
            cost_rank.get(a.cost_tier, 3),
            a.estimated_duration_days,
            a.order,
        ),
    )


def build_recovery_plan(
    *,
    project_id: int,
    assumptions: list[Any],
    evidence: list[Any],
) -> dict[str, Any]:
    """
    Build ordered recovery plays for every killed or inconsistent claim.

    Judgement is delegated to :func:`build_evidence_verdicts`, so the
    triggers here always agree with the scorecard endpoint. Returns a dict
    matching ``RecoveryPlanOut``.
    """
    verdicts = build_evidence_verdicts(
        project_id=project_id, assumptions=assumptions, evidence=evidence
    )

    rows_out: list[RecoveryRow] = []
    theme_counts: dict[str, int] = {}

    for row in verdicts["rows"]:
        trigger = str(row["verdict"])
        if trigger not in _TRIGGER_RANK:
            continue
        theme = _classify_theme(row.get("category"), row.get("assumption_text"))
        actions: list[RecoveryAction] = []

        audit = _audit_action({**row, "trigger": trigger})
        if audit is not None:
            actions.append(audit)

        start_order = len(actions) + 1
        for offset, (title, rationale, method) in enumerate(
            _THEME_PLAYBOOKS[theme]
        ):
            # An audited record gets exactly one fresh experiment after the
            # audit; a straight kill gets the full playbook.
            limit = 1 if audit is not None else len(_THEME_PLAYBOOKS[theme])
            if offset >= limit:
                break
            actions.append(
                _action_from_spec(start_order + offset, title, rationale, method)
            )

        out_row = RecoveryRow(
            assumption_id=int(row["assumption_id"]),
            assumption_text=row.get("assumption_text", "") or "",
            category=row.get("category"),
            trigger=trigger,  # type: ignore[arg-type]
            theme=theme,  # type: ignore[arg-type]
            actions=actions,
        )
        fastest = min(
            (a.estimated_duration_days for a in actions), default=0
        )
        out_row.fastest_path_days = int(fastest)
        cheapest = _cheapest_action(out_row)
        out_row.cheapest_action_title = cheapest.title if cheapest else ""
        rows_out.append(out_row)
        theme_counts[theme] = theme_counts.get(theme, 0) + 1

    rows_out.sort(
        key=lambda r: (_TRIGGER_RANK[r.trigger], -len(r.actions), r.assumption_id)
    )

    total = int(verdicts["total_assumptions"])
    killed = sum(1 for r in rows_out if r.trigger == "KILLED")
    inconsistent = len(rows_out) - killed

    if not rows_out:
        narrative = (
            "Nothing needs recovery — every judged assumption is on track "
            "or still unjudged."
        )
    else:
        top_theme = max(theme_counts.items(), key=lambda kv: kv[1])[0]
        first = rows_out[0]
        cheapest_overall = _cheapest_action(first)
        if cheapest_overall is None:
            cheapest_overall = first.actions[0] if first.actions else None
        tail = ""
        if cheapest_overall is not None:
            tail = (
                f" Cheapest first step: “{cheapest_overall.title}” "
                f"({cheapest_overall.cost_tier.lower()} cost, "
                f"{cheapest_overall.estimated_duration_days}d)."
            )
        narrative = (
            f"{killed} killed and {inconsistent} inconsistent assumption(s) "
            f"need recovery; the {top_theme} theme dominates."
            f"{tail}"
        )

    return {
        "project_id": project_id,
        "total_assumptions": total,
        "attention_count": len(rows_out),
        "killed_count": killed,
        "inconsistent_count": inconsistent,
        "theme_counts": dict(sorted(theme_counts.items())),
        "rows": [r.model_dump() for r in rows_out],
        "narrative": narrative,
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "model": "recovery_planner_v1",
            "judgment_source": "evidence_verdicts_v1",
            "playbook_themes": sorted(_THEME_PLAYBOOKS),
        },
    }


def jsonable(row: RecoveryRow) -> dict[str, Any]:
    """Serialize a row without Pydantic deprecation warnings."""
    return row.model_dump()


__all__ = [
    "build_recovery_plan",
]
